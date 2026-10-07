from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    CollectionConditionRequest,
    CollectionJob,
    Company,
    LeadSourceObservation,
    Project,
    User,
)
from app.project_access import project_access
from app.schema_collection_conditions import (
    CollectionCondition,
    ConfirmCollectionConditions,
    required_presence_plan,
)
from app.security import current_user
from app.services.collection_conditions import evaluate, snapshot_hash

router = APIRouter(prefix="/api")


def public(row):
    return dict(
        id=row.id,
        project_id=row.project_id,
        version=row.version,
        schema_version=row.schema_version,
        snapshot=row.snapshot,
        payload_hash=row.payload_hash,
        confirmed_by_user_id=row.confirmed_by_user_id,
        confirmed_at=row.confirmed_at,
    )


@router.get("/projects/{project_id}/collection-conditions")
def requests(
    project_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    return [
        public(r)
        for r in db.scalars(
            select(CollectionConditionRequest)
            .where(CollectionConditionRequest.project_id == project_id)
            .order_by(CollectionConditionRequest.version.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.post("/projects/{project_id}/collection-conditions", status_code=201)
def confirm(
    project_id: UUID,
    body: ConfirmCollectionConditions,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    db.scalar(select(Project.id).where(Project.id == project_id).with_for_update(key_share=True))
    version = (
        db.scalar(
            select(func.max(CollectionConditionRequest.version)).where(
                CollectionConditionRequest.project_id == project_id
            )
        )
        or 0
    )
    if version != body.expected_version:
        raise HTTPException(409, "条件が更新されています。最新の条件を確認してください。")
    if body.collection_job_id:
        job = db.get(CollectionJob, body.collection_job_id)
        if job is None or job.project_id != project_id:
            raise HTTPException(404, "収集が見つかりません。")
    snapshot = body.model_dump(mode="json", exclude={"expected_version", "confirmed"})
    snapshot.update(schema_version=1, project_id=str(project_id), version=version + 1)
    row = CollectionConditionRequest(
        project_id=project_id,
        collection_job_id=body.collection_job_id,
        version=version + 1,
        snapshot=snapshot,
        payload_hash=snapshot_hash(snapshot),
        confirmed_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    return public(row)


@router.get("/collection-conditions/{request_id}/results")
def results(
    request_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(CollectionConditionRequest, request_id)
    if row is None:
        raise HTTPException(404, "条件が見つかりません。")
    project_access(row.project_id, db, user, write=False)
    if snapshot_hash(row.snapshot) != row.payload_hash:
        raise HTTPException(409, "条件の整合性を確認できません。")
    query = select(Company).where(Company.project_id == row.project_id)
    job_id = row.snapshot.get("collection_job_id")
    if job_id:
        job = db.get(CollectionJob, UUID(job_id))
        if job is None or job.project_id != row.project_id:
            raise HTTPException(409, "対象の収集が利用できません。")
        query = query.where(
            Company.id.in_(
                select(LeadSourceObservation.company_id).where(
                    LeadSourceObservation.collection_job_id == job.id
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    conditions = [CollectionCondition.model_validate(c) for c in row.snapshot["conditions"]]
    candidates = [
        evaluate(db, c, conditions)
        for c in db.scalars(query.order_by(Company.id).offset(offset).limit(limit))
    ]
    return dict(
        request=public(row),
        total_candidates=total,
        offset=offset,
        limit=limit,
        evaluated_count=len(candidates),
        page_counts={
            state: sum(c["state"] == state for c in candidates)
            for state in ("MATCH", "NO_MATCH", "REVIEW_REQUIRED")
        },
        candidates=candidates,
        required_presence_plan=required_presence_plan(conditions).model_dump(),
        note="保存済み根拠のみを評価。条件確定は検索・補完・送信承認を開始しません。件数は表示ページ内の集計です。",
    )
