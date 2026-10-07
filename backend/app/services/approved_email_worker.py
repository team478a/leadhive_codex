"""Executor with commit-before-I/O and conservative UNKNOWN recovery."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.config import settings
from app.model_approved_email import ApprovedEmailBatch, ApprovedEmailReservation, EmailSendAttempt
from app.models import EmailDelivery
from app.services import approved_email as service
from app.services import human_approval as approval
from app.services.email_delivery import (
    EmailDeliveryError,
    email_delivery_limits,
    send_with_configuration,
    smtp_configuration,
)


def claim(db):
    service.expire_queued(db)
    from app.services.email_feedback import refresh_pending

    refresh_pending(db)
    from app.services.sending_window import allowed

    if not allowed(db):
        db.commit()
        return None
    if not settings.outbound_enabled or not settings.human_approved_email_enabled:
        return None
    now = approval.now()
    # Same global lock as the legacy sender, also used when reserving an attempt.
    db.execute(select(func.pg_advisory_xact_lock(4_781_001)))
    limits = email_delivery_limits(db)
    active = db.scalar(
        select(func.count())
        .select_from(EmailDelivery)
        .where(EmailDelivery.started_at >= now - timedelta(days=1))
    )
    last = db.scalar(select(func.max(EmailDelivery.started_at)))
    if active >= limits.max_emails_per_day or (
        last and last > now - timedelta(seconds=limits.minimum_interval_seconds)
    ):
        db.commit()
        return None
    rows = db.execute(
        select(EmailDelivery, ApprovedEmailBatch)
        .join(ApprovedEmailReservation, ApprovedEmailReservation.delivery_id == EmailDelivery.id)
        .join(ApprovedEmailBatch, ApprovedEmailBatch.id == ApprovedEmailReservation.batch_id)
        .where(
            EmailDelivery.status == "queued",
            EmailDelivery.scheduled_for <= now,
            ApprovedEmailBatch.status == "queued",
        )
        .order_by(EmailDelivery.scheduled_for, EmailDelivery.id)
        .with_for_update(of=EmailDelivery, skip_locked=True)
        .limit(100)
    ).all()
    for delivery, batch in rows:
        if not service.capacity(db, batch, now):
            continue
        delivery.status, delivery.worker_id = "running", uuid4()
        delivery.started_at = now
        delivery.attempt_count += 1
        delivery.lease_expires_at = now + timedelta(seconds=settings.worker_lease_seconds)
        db.commit()
        return delivery
    db.commit()
    return None


def run(db, delivery):
    if not settings.human_approved_email_enabled or not settings.outbound_enabled:
        return
    delivery_id, worker_id = delivery.id, delivery.worker_id
    started = False
    try:
        config = smtp_configuration(db)
        attempt = service.begin_attempt(db, delivery)
        if not attempt:
            return
        started = True
        row = service.reservation(db, delivery.id)
        if (
            config.from_email.lower() != row.sender_email
            or config.from_name != row.envelope["sender"]["name"]
        ):
            raise EmailDeliveryError("SMTP送信者が変更されています。新しい承認が必要です。")
        send_with_configuration(
            config,
            str(delivery.id),
            delivery.recipient_email,
            delivery.subject,
            delivery.body,
            stable_message_id=attempt.message_id,
            unsubscribe_url=row.envelope["unsubscribe_url"],
        )
        # A stale worker must not overwrite a recovery decision.
        db.refresh(delivery)
        if delivery.status == "running" and delivery.worker_id == worker_id:
            service.finish_attempt(db, delivery, "SMTP_ACCEPTED")
    except Exception as exc:
        db.rollback()
        delivery = db.get(EmailDelivery, delivery_id)
        row = service.reservation(db, delivery_id)
        attempt = db.scalar(
            select(EmailSendAttempt).where(EmailSendAttempt.reservation_id == row.id)
        )
        if delivery.status != "running" or delivery.worker_id != worker_id:
            return
        if attempt:
            result = (
                "FAILED" if isinstance(exc, EmailDeliveryError) and not exc.unknown else "UNKNOWN"
            )
            # Even a post-acceptance DB failure is UNKNOWN, never safely retryable.
            service.finish_attempt(
                db,
                delivery,
                result,
                exc.public_message
                if isinstance(exc, EmailDeliveryError)
                else "送信結果を確定できません。自動再送しません。",
            )
        elif not started:
            delivery.status, delivery.error_message = "blocked", "送信前の安全確認に失敗しました。"
            delivery.worker_id, delivery.lease_expires_at = None, None
            delivery.finished_at = approval.now()
            db.commit()


def recover(db, delivery):
    row = service.reservation(db, delivery.id)
    if not row:
        return False
    attempt = db.scalar(select(EmailSendAttempt).where(EmailSendAttempt.reservation_id == row.id))
    if attempt and attempt.result == "STARTED":
        service.finish_attempt(
            db, delivery, "UNKNOWN", "送信中断を検出しました。SMTP履歴のHuman確認が必要です。"
        )
    elif not attempt:
        delivery.status, delivery.error_message = (
            "blocked",
            "送信前のワーカー中断を検出しました。再承認してください。",
        )
        delivery.worker_id, delivery.lease_expires_at = None, None
        delivery.finished_at = approval.now()
    return True


def recover_stale(db):
    from app.models import ApprovalRequest

    ids = db.execute(
        select(EmailDelivery.id, ApprovedEmailReservation.approval_id)
        .join(ApprovedEmailReservation, ApprovedEmailReservation.delivery_id == EmailDelivery.id)
        .where(EmailDelivery.status == "running", EmailDelivery.lease_expires_at < approval.now())
        .order_by(EmailDelivery.id)
        .limit(100)
    ).all()
    count = 0
    for delivery_id, approval_id in ids:
        db.scalar(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
        delivery = db.scalar(
            select(EmailDelivery)
            .where(EmailDelivery.id == delivery_id)
            .execution_options(populate_existing=True)
            .with_for_update(skip_locked=True)
        )
        if delivery and delivery.status == "running" and delivery.lease_expires_at < approval.now():
            recover(db, delivery)
            count += 1
    db.commit()
    return count
