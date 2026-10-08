from datetime import timedelta
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.model_approved_form import FormDispatchLimits
from app.models import ApprovalRequest, ApprovedFormDispatch, OutreachAuditEvent, User
from app.project_access import project_access
from app.schema_approved_form import FormDispatchBulk, FormDispatchCreate, FormLimitsUpdate
from app.security import current_admin, current_user
from app.services import approved_form, form_site_rate, human_approval

router = APIRouter(prefix="/api", tags=["Human approved forms"])


@router.get("/form-dispatch-limits")
def limits(db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(FormDispatchLimits, 1)
    if not row:
        raise HTTPException(503, "フォーム上限設定が未適用です。")
    return {
        **{c.name: getattr(row, c.name) for c in FormDispatchLimits.__table__.columns},
        "can_manage": user.is_admin,
        "execution_enabled": settings.outbound_enabled and settings.human_approved_form_enabled,
    }


@router.put("/form-dispatch-limits")
def update_limits(
    body: FormLimitsUpdate, db: Session = Depends(get_db), user: User = Depends(current_admin)
):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    attempts = db.scalar(
        select(func.count())
        .select_from(OutreachAuditEvent)
        .where(
            OutreachAuditEvent.actor_id == user.id,
            OutreachAuditEvent.event == "form limits reauthentication",
            OutreachAuditEvent.timestamp >= human_approval.now() - timedelta(minutes=5),
        )
    )
    if attempts >= 5:
        raise HTTPException(429, "再認証の回数が多すぎます。5分後に再試行してください。")
    db.add(
        OutreachAuditEvent(
            event="form limits reauthentication", principal_type="HUMAN", actor_id=user.id
        )
    )
    if not human_approval.step_up_verifier.verify(user, body.password):
        db.add(
            OutreachAuditEvent(
                event="authentication denied",
                principal_type="HUMAN",
                actor_id=user.id,
                reason="form limits step-up failed",
            )
        )
        db.commit()
        raise HTTPException(403, "再認証に失敗しました。")
    approved_form.lock(db)
    row = db.scalar(select(FormDispatchLimits).where(FormDispatchLimits.id == 1).with_for_update())
    if not row:
        raise HTTPException(503, "フォーム上限設定が未適用です。")
    if row.version != body.expected_version:
        raise HTTPException(409, "設定が変更されています。再取得してください。")
    changes = body.model_dump(exclude={"password", "expected_version"}, exclude_none=True)
    before = {key: getattr(row, key) for key in changes}
    for key, value in changes.items():
        setattr(row, key, value)
    row.version += 1
    row.updated_by_user_id, row.updated_at = user.id, human_approval.now()
    db.add(
        OutreachAuditEvent(
            event="form limits changed",
            principal_type="HUMAN",
            actor_id=user.id,
            reason=f"v{row.version}: "
            + "; ".join(f"{key}={before[key]}->{value}" for key, value in changes.items()),
        )
    )
    db.commit()
    return limits(db, user)


@router.get("/form-dispatch-limits/audit")
def limits_audit(db: Session = Depends(get_db), user: User = Depends(current_admin)):
    rows = db.scalars(
        select(OutreachAuditEvent)
        .where(
            OutreachAuditEvent.event == "form limits changed",
        )
        .order_by(OutreachAuditEvent.timestamp.desc(), OutreachAuditEvent.id)
        .limit(20)
    ).all()
    return [
        {"id": row.id, "actor_id": row.actor_id, "timestamp": row.timestamp, "reason": row.reason}
        for row in rows
    ]


@router.post("/projects/{project_id}/approved-form-dispatches", status_code=201)
def bulk_reserve(
    project_id: UUID,
    body: FormDispatchBulk,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    # Per-item results are intentional: retries reuse the same deterministic keys.
    results = []
    for selection in body.items:
        try:
            item = db.get(ApprovalRequest, selection.request_id)
            if not item or item.project_id != project_id:
                raise HTTPException(404, "提案が見つかりません。")
            row = approved_form.reserve(
                db,
                item,
                FormDispatchCreate(
                    expected_hash=selection.expected_hash,
                    expected_version=selection.expected_version,
                    idempotency_key=uuid5(body.idempotency_key, str(selection.request_id)),
                ),
                user,
            )
            results.append(
                {"request_id": selection.request_id, "reservation": output(row), "error": None}
            )
        except HTTPException as exc:
            db.rollback()
            results.append(
                {"request_id": selection.request_id, "reservation": None, "error": exc.detail}
            )
    return {"results": results}


def output(row):
    method = row.payload_snapshot.get("delivery_method")
    return {
        **{c.name: getattr(row, c.name) for c in ApprovedFormDispatch.__table__.columns},
        "delivery_method": method,
        "reservation_only": method in {"form_adapter", "cf7_real_reservation"},
        "execution_enabled": method == "form_direct"
        and settings.outbound_enabled
        and settings.human_approved_form_enabled,
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
    rows = db.scalars(
        select(ApprovedFormDispatch)
        .where(
            ApprovedFormDispatch.project_id == project_id,
        )
        .order_by(ApprovedFormDispatch.created_at.desc(), ApprovedFormDispatch.id)
        .limit(limit)
        .offset(offset)
    ).all()
    waits = form_site_rate.wait_times(db, rows)
    return [
        output(row) | {"site_wait_until": waits.get(row.id) if row.status == "queued" else None}
        for row in rows
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
    if row.payload_snapshot.get("delivery_method") == "form_adapter":
        row.worker_id = None
    human_approval.audit(
        db, db.get(ApprovalRequest, row.approval_id), "form dispatch cancelled", "HUMAN", user.id
    )
    db.commit()
    return output(row)
