from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.approval_routes import serialize
from app.database import get_db
from app.models import ApprovalRequest, ApprovedFormDispatch, Company, OutreachAuditEvent, User
from app.project_access import project_access
from app.schema_approval import ExpectedPayload
from app.security import current_user
from app.services import approved_form, human_approval
from app.services import form_operations as operations
from app.services.form_approval_preparation import preparation

router = APIRouter(prefix="/api", tags=["Form operations"])


class Reprepare(ExpectedPayload):
    expected_preparation_hash: str = Field(pattern="^[a-f0-9]{64}$")


class Review(ExpectedPayload):
    choice: Literal["investigating", "received", "unconfirmed"]


def access(db, dispatch_id, user, write=True, locked=False):
    row = (
        db.scalar(
            select(ApprovedFormDispatch)
            .where(ApprovedFormDispatch.id == dispatch_id)
            .with_for_update()
        )
        if locked
        else db.get(ApprovedFormDispatch, dispatch_id)
    )
    if not row:
        raise HTTPException(404, "予約が見つかりません。")
    project_access(row.project_id, db, user, write=write)
    item = (
        db.scalar(
            select(ApprovalRequest).where(ApprovalRequest.id == row.approval_id).with_for_update()
        )
        if locked
        else db.get(ApprovalRequest, row.approval_id)
    )
    return row, item


@router.get("/projects/{project_id}/form-operations")
def listing(
    project_id: UUID,
    category: str = Query(
        "attention",
        pattern="^(all|attention|expired|interrupted|blocked|unknown|failed|cancelled|queued|checking|submitted)$",
    ),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    classification = operations.category()
    base = (
        select(
            ApprovedFormDispatch,
            ApprovalRequest,
            Company.company_name,
            classification.label("category"),
        )
        .join(ApprovalRequest, ApprovalRequest.id == ApprovedFormDispatch.approval_id)
        .join(Company, Company.id == ApprovedFormDispatch.company_id)
        .where(ApprovedFormDispatch.project_id == project_id)
    )
    counts = dict(
        db.execute(
            select(classification, func.count())
            .select_from(ApprovedFormDispatch)
            .join(ApprovalRequest, ApprovalRequest.id == ApprovedFormDispatch.approval_id)
            .where(ApprovedFormDispatch.project_id == project_id)
            .group_by(classification)
        ).all()
    )
    if category == "attention":
        base = base.where(
            classification.in_(("expired", "interrupted", "blocked", "unknown", "failed"))
        )
    elif category != "all":
        base = base.where(classification == category)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        base.order_by(ApprovedFormDispatch.created_at.desc(), ApprovedFormDispatch.id)
        .limit(limit)
        .offset(offset)
    ).all()
    reviews = operations.latest_reviews(db, [item.id for _, item, _, _ in rows])
    return {
        "counts": counts,
        "total": total,
        "items": [
            {
                "id": row.id,
                "approval_id": item.id,
                "company_name": name,
                "company_id": row.company_id,
                "form_url": row.form_url,
                "status": row.status,
                "category": group,
                "reason": row.reason,
                "expires_at": item.expires_at,
                "started_at": row.started_at,
                "approval_status": item.status,
                "payload_hash": item.payload_hash,
                "payload_version": item.payload_version,
                "can_reprepare": operations.reprepare_allowed(row, item),
                "review": reviews.get(item.id),
            }
            for row, item, name, group in rows
        ],
    }


@router.post("/projects/{project_id}/form-operations/reconcile")
def reconcile(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project_access(project_id, db, user)
    approved_form.lock(db)
    count = operations.reconcile_locked(db, project_id)
    db.add(
        OutreachAuditEvent(
            event="form reconciliation requested",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            reason=f"processed={count}; limit=100",
        )
    )
    db.commit()
    return {"processed": count, "limit": 100}


@router.get("/approved-form-dispatches/{dispatch_id}/reprepare-preview")
def preview(dispatch_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row, item = access(db, dispatch_id, user)
    return preparation(db, *operations.source(db, row, item))[1]


@router.post("/approved-form-dispatches/{dispatch_id}/reprepare", status_code=201)
def reprepare(
    dispatch_id: UUID,
    body: Reprepare,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    approved_form.lock(db)
    row, item = access(db, dispatch_id, user, locked=True)
    return serialize(db, operations.reprepare(db, row, item, body, user))


@router.post("/approved-form-dispatches/{dispatch_id}/review")
def review(
    dispatch_id: UUID,
    body: Review,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    approved_form.lock(db)
    row, item = access(db, dispatch_id, user, locked=True)
    human_approval.expected(item, body)
    if row.status != "unknown":
        raise HTTPException(409, "結果不明の予約だけ確認記録を残せます。")
    human_approval.audit(
        db, item, "form review recorded", "HUMAN", user.id, item.status, body.choice
    )
    db.commit()
    return {"recorded": True, "status": row.status, "retry_allowed": False}
