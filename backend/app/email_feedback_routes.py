"""Human evidence and a normalized, opt-in HMAC provider boundary."""

import hashlib
import hmac
import re
import time
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select

from app.approved_email_routes import access
from app.config import settings
from app.database import get_db
from app.model_email_feedback import EmailFeedbackEvent
from app.models import OutreachAuditEvent, User
from app.project_access import project_access
from app.schema_email_feedback import FeedbackInput, HealthReview
from app.security import current_user
from app.services import email_feedback, human_approval

router = APIRouter(prefix="/api", tags=["Email feedback"])


def serialize(item):
    return {
        k: getattr(item, k)
        for k in ("id", "delivery_id", "source", "kind", "recipient", "occurred_at", "received_at")
    }


@router.get("/projects/{project_id}/email-health")
def health(project_id: UUID, db=Depends(get_db), user: User = Depends(current_user)):
    access(db, project_id, user, False)
    result = email_feedback.summary(db, project_id)
    db.commit()
    return result


@router.get("/projects/{project_id}/email-feedback")
def events(
    project_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user, False)
    rows = db.scalars(
        select(EmailFeedbackEvent)
        .where(EmailFeedbackEvent.project_id == project_id)
        .order_by(EmailFeedbackEvent.received_at.desc(), EmailFeedbackEvent.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [serialize(row) for row in rows]


@router.post("/projects/{project_id}/email-feedback", status_code=201)
def manual(
    project_id: UUID, body: FeedbackInput, db=Depends(get_db), user: User = Depends(current_user)
):
    access(db, project_id, user)
    event = email_feedback.record(db, body, "HUMAN", user, project_id)
    db.commit()
    return serialize(event)


@router.post("/projects/{project_id}/email-health/review")
def review(
    project_id: UUID, body: HealthReview, db=Depends(get_db), user: User = Depends(current_user)
):
    access(db, project_id, user)
    project_access(project_id, db, user, owner=True)
    row = email_feedback.state(db, project_id)
    if not row.paused or row.stopped_at != body.expected_stopped_at:
        raise HTTPException(409, "停止状態が変わっています。再取得してください。")
    if row.review_locked_until and row.review_locked_until > human_approval.now():
        raise HTTPException(429, "再認証が一時停止中です。15分後に確認してください。")
    if not human_approval.step_up_verifier.verify(user, body.password):
        if row.review_locked_until and row.review_locked_until <= human_approval.now():
            row.review_failures = 0
        row.review_failures += 1
        if row.review_failures >= 5:
            row.review_locked_until = human_approval.now() + timedelta(minutes=15)
        db.add(
            OutreachAuditEvent(
                event="authentication denied",
                principal_type="HUMAN",
                actor_id=user.id,
                project_id=project_id,
                reason="email health review failed",
            )
        )
        db.commit()
        raise HTTPException(403, "再認証に失敗しました。")
    row.paused, row.reason = False, ""
    row.reviewed_at, row.reviewed_by = human_approval.now(), user.id
    row.review_failures, row.review_locked_until = 0, None
    db.add(
        OutreachAuditEvent(
            event="email health reviewed",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            reason="Owner reviewed SMTP evidence; batches remain paused",
        )
    )
    result = email_feedback.summary(db, project_id)
    db.commit()
    return result


@router.post("/webhooks/email-feedback")
async def webhook(request: Request, db=Depends(get_db)):
    if (
        not settings.email_feedback_webhook_enabled
        or len(settings.email_feedback_webhook_secret) < 32
    ):
        raise HTTPException(404, "通知受付は無効です。")
    if request.cookies or request.headers.get("authorization"):
        raise HTTPException(403, "通知専用認証が必要です。")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16_384:
            raise HTTPException(413, "通知が大きすぎます。")
    timestamp = request.headers.get("x-leadhive-timestamp", "")
    try:
        valid_time = len(timestamp) <= 12 and abs(time.time() - int(timestamp)) <= 300
    except ValueError:
        valid_time = False
    expected = hmac.new(
        settings.email_feedback_webhook_secret.encode(),
        timestamp.encode() + b"." + bytes(raw),
        hashlib.sha256,
    ).hexdigest()
    signature = request.headers.get("x-leadhive-signature", "")
    if (
        not valid_time
        or not re.fullmatch(r"[0-9a-f]{64}", signature)
        or not hmac.compare_digest(expected, signature)
    ):
        raise HTTPException(403, "通知の署名を確認できません。")
    try:
        body = FeedbackInput.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "通知内容を確認してください。") from None
    event = email_feedback.record(db, body, "PROVIDER")
    db.commit()
    return {"event_id": event.id, "accepted": True}
