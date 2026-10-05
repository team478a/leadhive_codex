from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ApprovalRequest, ApprovedFormDispatch, User
from app.project_access import project_access
from app.schema_approved_form import FormDispatchCreate
from app.security import current_user
from app.services import approved_form, human_approval

router = APIRouter(prefix="/api", tags=["Human approved forms"])


def output(row):
    return {
        **{c.name: getattr(row, c.name) for c in ApprovedFormDispatch.__table__.columns},
        "execution_enabled": settings.outbound_enabled and settings.human_approved_form_enabled,
    }


@router.post("/approval-requests/{request_id}/form-dispatch", status_code=201)
def reserve(
    request_id: UUID,
    body: FormDispatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    item = db.get(ApprovalRequest, request_id)
    if not item:
        raise HTTPException(404, "提案が見つかりません。")
    project_access(item.project_id, db, user)
    return output(approved_form.reserve(db, item, body, user))


@router.get("/projects/{project_id}/approved-form-dispatches")
def listing(
    project_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    return [
        output(row)
        for row in db.scalars(
            select(ApprovedFormDispatch)
            .where(
                ApprovedFormDispatch.project_id == project_id,
            )
            .order_by(ApprovedFormDispatch.created_at.desc(), ApprovedFormDispatch.id)
            .limit(limit)
            .offset(offset)
        ).all()
    ]


@router.post("/approved-form-dispatches/{dispatch_id}/cancel")
def cancel(dispatch_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(
        select(ApprovedFormDispatch).where(ApprovedFormDispatch.id == dispatch_id).with_for_update()
    )
    if not row:
        raise HTTPException(404, "予約が見つかりません。")
    project_access(row.project_id, db, user)
    if row.status not in {"queued", "checking"}:
        raise HTTPException(409, "送信試行開始後の取消・再送はできません。")
    row.status, row.finished_at = "cancelled", human_approval.now()
    human_approval.audit(
        db, db.get(ApprovalRequest, row.approval_id), "form dispatch cancelled", "HUMAN", user.id
    )
    db.commit()
    return output(row)
