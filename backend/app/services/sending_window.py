"""Daily outbound window, independent of authorization and send-rate limits."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.model_settings import SendingWindow

JST = timezone(timedelta(hours=9))


def allowed(db: Session, at: datetime | None = None) -> bool:
    saved = db.get(SendingWindow, 1, populate_existing=True)
    if saved is None or not saved.enabled:
        return True
    local = (at or datetime.now(timezone.utc)).astimezone(JST)
    minute = local.hour * 60 + local.minute
    return saved.start_minute <= minute < saved.end_minute


def require_sending_time() -> None:
    # Read committed configuration again at the actual SMTP/POST boundary.
    # Do not rely on a worker's cached configuration or the earlier claim time.
    with SessionLocal() as db:
        if not allowed(db):
            raise HTTPException(409, "送信可能時間外です。送信を停止しています。")


def defer_email(db: Session, delivery) -> bool:
    if allowed(db):
        return False
    from app.model_approved_email import ApprovedEmailReservation, EmailSendAttempt
    from app.models import EmailDelivery

    worker_id = delivery.worker_id
    row = db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.id == delivery.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    attempted = db.scalar(
        select(EmailSendAttempt.id)
        .join(ApprovedEmailReservation)
        .where(ApprovedEmailReservation.delivery_id == delivery.id)
    )
    if not row or row.status != "running" or row.worker_id != worker_id or attempted:
        db.commit()
        return True  # Never requeue an UNKNOWN or durable attempt, even before SMTP.
    delivery.status = "queued"
    delivery.worker_id = None
    delivery.lease_expires_at = None
    delivery.started_at = None
    delivery.attempt_count = max(0, delivery.attempt_count - 1)
    delivery.error_message = "送信可能時間外のため待機中です。"
    db.commit()
    return True
