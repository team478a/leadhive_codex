"""Human-only preparation APIs; never authorize or send outreach."""

from collections import Counter
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, OperationJob, Project, SalesPreparationItem, TargetProfile, User
from app.project_access import project_access
from app.schema_preparation import SalesPreparationInput
from app.schemas import OperationJobOut
from app.security import current_user
from app.services.sales_preparation import context_hash

router = APIRouter(prefix="/api")
PREPARATION_TYPES = ("prepare_outreach", "web_analysis", "ai_analysis", "form_intelligence")


def lock_project(db, project_id):
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())


def active_preparation_work(db, project_id):
    return db.scalar(
        select(OperationJob.id)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type.in_(PREPARATION_TYPES),
            OperationJob.status.in_(("queued", "running")),
        )
        .limit(1)
    )


@router.post(
    "/projects/{project_id}/sales-preparation", response_model=OperationJobOut, status_code=202
)
def start_preparation(
    project_id: UUID,
    body: SalesPreparationInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = project_access(project_id, db, user)
    lock_project(db, project_id)
    if active_preparation_work(db, project_id):
        raise HTTPException(409, "解析・営業準備が実行中です。完了または停止後に開始してください。")
    query = (
        select(Company)
        .where(Company.project_id == project_id)
        .order_by(Company.created_at, Company.id)
    )
    if body.company_ids:
        query = query.where(Company.id.in_(body.company_ids))
        if body.offset:
            raise HTTPException(422, "個別企業の指定と開始位置は併用できません。")
    companies = list(db.scalars(query.offset(body.offset).limit(body.limit)))
    if body.company_ids and {c.id for c in companies} != set(body.company_ids):
        raise HTTPException(422, "対象件数・プロジェクト・上限を確認してください。")
    if not companies:
        raise HTTPException(409, "営業準備の対象企業がありません。")
    profile = db.get(TargetProfile, project.target_profile_id)
    job = OperationJob(
        project_id=project_id,
        operation_type="prepare_outreach",
        total_count=len(companies),
        payload={
            **body.model_dump(mode="json"),
            "requested_by_user_id": str(user.id),
            "context_hash": context_hash(project, profile),
            "used_search_requests": 0,
            "used_ai_requests": 0,
        },
    )
    db.add(job)
    db.flush()
    db.add_all([SalesPreparationItem(job_id=job.id, company_id=c.id) for c in companies])
    db.commit()
    db.refresh(job)
    return job


@router.get("/projects/{project_id}/sales-preparation")
def list_preparation(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    jobs = list(
        db.scalars(
            select(OperationJob)
            .where(
                OperationJob.project_id == project_id,
                OperationJob.operation_type == "prepare_outreach",
            )
            .order_by(OperationJob.created_at.desc())
            .limit(10)
        )
    )
    results = []
    for job in jobs:
        rows = db.execute(
            select(SalesPreparationItem, Company.company_name)
            .join(Company, Company.id == SalesPreparationItem.company_id)
            .where(SalesPreparationItem.job_id == job.id)
            .order_by(Company.created_at, Company.id)
        ).all()
        results.append(
            {
                "job": OperationJobOut.model_validate(job),
                "counts": dict(Counter(item.status for item, _ in rows)),
                "used_search_requests": job.payload["used_search_requests"],
                "used_ai_requests": job.payload["used_ai_requests"],
                "max_search_requests": job.payload["max_search_requests"],
                "max_ai_requests": job.payload["max_ai_requests"],
                "items": [
                    {
                        "id": item.id,
                        "company_id": item.company_id,
                        "company_name": name,
                        "status": item.status,
                        "stage": item.stage,
                        "reason": item.reason,
                        "channel": item.channel,
                        "draft_id": item.draft_id,
                        "details": item.details,
                        "updated_at": item.updated_at,
                    }
                    for item, name in rows
                ],
            }
        )
    return results


@router.post("/sales-preparation/{job_id}/resume", response_model=OperationJobOut, status_code=202)
def resume_preparation(
    job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    job = db.get(OperationJob, job_id)
    if job is None or job.operation_type != "prepare_outreach":
        raise HTTPException(404, "営業準備が見つかりません。")
    project_access(job.project_id, db, user)
    lock_project(db, job.project_id)
    if job.status not in {"cancelled", "failed"} or active_preparation_work(db, job.project_id):
        raise HTTPException(409, "停止した営業準備だけを再開できます。")
    if not db.scalar(
        select(SalesPreparationItem.id)
        .where(
            SalesPreparationItem.job_id == job.id,
            SalesPreparationItem.status.in_(("pending", "running")),
        )
        .limit(1)
    ):
        raise HTTPException(
            409,
            "未処理の企業はありません。要確認・エラーは内容を確認し、新しい準備を作成してください。",
        )
    job.status, job.cancel_requested = "queued", False
    job.worker_id, job.lease_expires_at, job.finished_at = None, None, None
    job.attempt_count = 0
    job.error_message = ""
    job.payload = {**job.payload, "requested_by_user_id": str(user.id)}
    job.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job
