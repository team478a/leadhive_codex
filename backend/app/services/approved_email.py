"""Human-approved reservations. No external I/O in preparation APIs."""

import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.config import settings
from app.model_approved_email import ApprovedEmailBatch, ApprovedEmailReservation, EmailSendAttempt
from app.models import (
    ApprovalRequest,
    Company,
    EmailDelivery,
    OutreachDraft,
    OutreachDraftApproval,
    Project,
    ProjectMember,
    SuppressionEntry,
    User,
)
from app.project_access import project_access
from app.services import human_approval as approval
from app.services.contact_permission import evaluate_contact_permission
from app.services.email_delivery import email_delivery_limits, smtp_configuration

RESERVATION_LOCK = 4_781_002


def reservation(db, delivery_id):
    return db.scalar(
        select(ApprovedEmailReservation).where(ApprovedEmailReservation.delivery_id == delivery_id)
    )


def safety_reason(db, item):
    approver = db.get(User, item.approved_by_user_id) if item.approved_by_user_id else None
    if item.status == "APPROVED":
        if not approver:
            return "Human承認者を確認できません。"
        try:
            project_access(item.project_id, db, approver)
        except HTTPException:
            return "Human承認者のプロジェクト権限が変更されています。"
    permission = evaluate_contact_permission(
        db, item.project_id, item.company_id, "email", item.recipient
    )
    if not permission.allowed:
        return permission.message
    recipient = item.recipient.strip().lower()
    # SMTP is installation-wide today: block opt-outs across projects sharing it.
    if db.scalar(
        select(SuppressionEntry.id)
        .where(
            or_(
                func.lower(SuppressionEntry.email) == recipient,
                func.lower(SuppressionEntry.domain) == recipient.rsplit("@", 1)[-1],
            )
        )
        .limit(1)
    ) or db.scalar(
        select(Company.id)
        .where(func.lower(Company.email) == recipient, Company.do_not_contact.is_(True))
        .limit(1)
    ):
        return "同じ送信環境の連絡禁止・配信停止に該当します。"
    config = smtp_configuration(db)
    if config.from_email.strip().lower() != item.sender.get(
        "email", ""
    ).strip().lower() or config.from_name != item.sender.get("name"):
        return "承認した送信者と現在のSMTP送信者が一致しません。"
    return ""


def duplicate(db, recipient, exclude=None):
    query = select(EmailDelivery.id).where(
        func.lower(EmailDelivery.recipient_email) == recipient.lower(),
        EmailDelivery.status.in_(("queued", "running", "sent", "unknown")),
    )
    if exclude:
        query = query.where(EmailDelivery.id != exclude)
    return db.scalar(query.limit(1)) is not None


def create_batch(db, project_id, body, user):
    db.execute(select(func.pg_advisory_xact_lock(RESERVATION_LOCK)))
    fingerprint = approval.payload_hash(body.model_dump(mode="json"))
    existing = db.scalar(
        select(ApprovedEmailBatch).where(ApprovedEmailBatch.idempotency_key == body.idempotency_key)
    )
    if existing:
        if existing.project_id != project_id or existing.request_hash != fingerprint:
            raise HTTPException(409, "予約キーが異なる内容で使用されています。")
        return existing
    scheduled = body.scheduled_for or approval.now()
    if scheduled.tzinfo is None or scheduled < approval.now() - timedelta(minutes=1):
        raise HTTPException(422, "予約時刻を確認してください。")
    url = settings.public_app_url.rstrip("/")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise HTTPException(409, "配信停止用の公開HTTPS URLを設定してください。")
    items = db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.id.in_([s.request_id for s in body.items]))
        .order_by(ApprovalRequest.id)
        .with_for_update()
    ).all()
    if len(items) != len(body.items) or any(i.project_id != project_id for i in items):
        raise HTTPException(404, "提案が見つかりません。")
    expected = {s.request_id: s for s in body.items}
    recipients = set()
    for item in items:
        approval.expected(item, expected[item.id])
        if not approval.valid_approved_payload(db, item):
            db.commit()
            raise HTTPException(409, "有効なHuman承認が必要です。")
        if (
            item.channel != "email"
            or item.delivery_method != "email"
            or not item.subject.strip()
            or not item.body.strip()
            or len(item.subject) > 300
            or item.payload_snapshot.get("attachment_metadata")
            or item.field_values
            or "\r" in item.subject
            or "\n" in item.subject
            or "\r" in item.sender.get("name", "")
            or "\n" in item.sender.get("name", "")
        ):
            raise HTTPException(409, "このメール内容は予約送信に対応していません。")
        if scheduled >= item.expires_at:
            raise HTTPException(409, "承認期限内の送信予約にしてください。")
        reason = safety_reason(db, item)
        if reason:
            raise HTTPException(409, reason)
        recipient = item.recipient.strip().lower()
        if (
            recipient in recipients
            or duplicate(db, recipient)
            or db.scalar(
                select(ApprovedEmailReservation.id).where(
                    ApprovedEmailReservation.approval_id == item.id
                )
            )
        ):
            raise HTTPException(409, "宛先または承認に既存の送信・予約があります。")
        recipients.add(recipient)
    batch = ApprovedEmailBatch(
        id=uuid4(),
        project_id=project_id,
        created_by_user_id=user.id,
        idempotency_key=body.idempotency_key,
        request_hash=fingerprint,
        name=body.name,
        daily_limit=body.daily_limit,
        hourly_limit=body.hourly_limit,
    )
    db.add(batch)
    db.flush()
    for item in items:
        draft = OutreachDraft(
            company_id=item.company_id,
            created_by_user_id=user.id,
            channel="email",
            subject=item.subject,
            body=item.body,
        )
        db.add(draft)
        db.flush()
        delivery = EmailDelivery(
            id=uuid4(),
            draft_id=draft.id,
            company_id=item.company_id,
            created_by_user_id=user.id,
            recipient_email=item.recipient,
            subject=item.subject,
            body=item.body,
            scheduled_for=scheduled,
            confirmed_at=item.approved_at,
            unsubscribe_token=secrets.token_urlsafe(32),
        )
        db.add(delivery)
        db.flush()
        db.add(
            OutreachDraftApproval(
                draft_id=draft.id,
                approved_by_user_id=item.approved_by_user_id,
                approval_type="email",
                subject=item.subject,
                body=item.body,
                approved_at=item.approved_at,
            )
        )
        envelope = {
            "approval_hash": item.payload_hash,
            "approval_version": item.payload_version,
            "company_id": str(item.company_id),
            "recipient": item.recipient,
            "subject": item.subject,
            "body": item.body,
            "sender": item.sender,
            "unsubscribe_url": f"{url}/api/public/unsubscribe/{delivery.unsubscribe_token}",
        }
        db.add(
            ApprovedEmailReservation(
                batch_id=batch.id,
                approval_id=item.id,
                delivery_id=delivery.id,
                envelope=envelope,
                envelope_hash=approval.payload_hash(envelope),
                sender_email=item.sender["email"].lower(),
                recipient_email=item.recipient.lower(),
            )
        )
        approval.audit(db, item, "email reserved", "HUMAN", user.id, item.status)
    db.commit()
    return batch


def batch_summary(db, batch):
    counts = dict(
        db.execute(
            select(EmailDelivery.status, func.count())
            .join(
                ApprovedEmailReservation, ApprovedEmailReservation.delivery_id == EmailDelivery.id
            )
            .where(ApprovedEmailReservation.batch_id == batch.id)
            .group_by(EmailDelivery.status)
        ).all()
    )
    if batch.status == "queued" and counts and not (counts.get("queued") or counts.get("running")):
        batch.status = "completed"
    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "daily_limit": batch.daily_limit,
        "hourly_limit": batch.hourly_limit,
        "created_at": batch.created_at,
        "counts": counts,
        "execution_enabled": settings.human_approved_email_enabled and settings.outbound_enabled,
    }


def expire_queued(db):
    rows = db.execute(
        select(EmailDelivery, ApprovalRequest)
        .join(ApprovedEmailReservation, ApprovedEmailReservation.delivery_id == EmailDelivery.id)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovedEmailReservation.approval_id)
        .where(
            EmailDelivery.status == "queued",
            or_(ApprovalRequest.expires_at <= approval.now(), ApprovalRequest.status != "APPROVED"),
        )
        .limit(100)
    ).all()
    for delivery, item in rows:
        db.scalar(
            select(ApprovalRequest)
            .where(ApprovalRequest.id == item.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        db.scalar(
            select(EmailDelivery)
            .where(EmailDelivery.id == delivery.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if delivery.status != "queued" or (
            item.status == "APPROVED" and item.expires_at > approval.now()
        ):
            continue
        approval.invalidate_if_needed(db, item)
        delivery.status, delivery.error_message = (
            "blocked",
            "承認が失効・取消済みです。再承認が必要です。",
        )
        delivery.finished_at = approval.now()
        approval.audit(
            db, item, "email blocked", "SYSTEM", None, item.status, "approval unavailable"
        )
    db.commit()


def capacity(db, batch, now):
    # Count every reserved SMTP attempt, including UNKNOWN/FAILED, against quotas.
    for hours, limit in ((24, batch.daily_limit), (1, batch.hourly_limit)):
        count = db.scalar(
            select(func.count())
            .select_from(EmailDelivery)
            .join(
                ApprovedEmailReservation, ApprovedEmailReservation.delivery_id == EmailDelivery.id
            )
            .where(
                ApprovedEmailReservation.batch_id == batch.id,
                EmailDelivery.started_at >= now - timedelta(hours=hours),
            )
        )
        if count >= limit:
            return False
    return True


def begin_attempt(db, delivery):
    worker_id = delivery.worker_id
    row = reservation(db, delivery.id)
    initial = db.get(ApprovalRequest, row.approval_id)
    db.scalar(select(Project).where(Project.id == initial.project_id).with_for_update())
    db.scalar(
        select(ProjectMember)
        .where(
            ProjectMember.project_id == initial.project_id,
            ProjectMember.user_id == initial.approved_by_user_id,
        )
        .with_for_update()
    )
    db.execute(select(func.pg_advisory_xact_lock(RESERVATION_LOCK)))
    batch = db.scalar(
        select(ApprovedEmailBatch).where(ApprovedEmailBatch.id == row.batch_id).with_for_update()
    )
    item = db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.id == row.approval_id).with_for_update()
    )
    db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.id == delivery.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        delivery.status != "running"
        or delivery.worker_id != worker_id
        or not worker_id
        or delivery.lease_expires_at <= approval.now()
    ):
        db.commit()
        return None
    if db.scalar(select(EmailSendAttempt.id).where(EmailSendAttempt.reservation_id == row.id)):
        # Duplicate invocation must neither transmit nor overwrite an in-flight result.
        db.commit()
        return None
    reason = ""
    if batch.status != "queued":
        reason = "送信予約が停止・取消済みです。"
    elif not approval.valid_approved_payload(db, item):
        reason = "承認が失効・取消済みです。"
    elif (
        approval.payload_hash(row.envelope) != row.envelope_hash
        or row.envelope["approval_hash"] != item.payload_hash
        or row.envelope["approval_version"] != item.payload_version
        or (delivery.company_id, delivery.recipient_email, delivery.subject, delivery.body)
        != (item.company_id, item.recipient, item.subject, item.body)
    ):
        reason = "承認内容と予約内容が一致しません。"
    else:
        reason = safety_reason(db, item)
    if not reason:
        limits = email_delivery_limits(db)
        global_count = db.scalar(
            select(func.count())
            .select_from(EmailDelivery)
            .where(EmailDelivery.started_at >= approval.now() - timedelta(days=1))
        )
        if global_count > limits.max_emails_per_day:
            reason = "現在のSMTP送信上限に達しています。"
        for hours, limit in ((24, batch.daily_limit), (1, batch.hourly_limit)):
            used = db.scalar(
                select(func.count())
                .select_from(EmailDelivery)
                .join(
                    ApprovedEmailReservation,
                    ApprovedEmailReservation.delivery_id == EmailDelivery.id,
                )
                .where(
                    ApprovedEmailReservation.batch_id == batch.id,
                    EmailDelivery.started_at >= approval.now() - timedelta(hours=hours),
                )
            )
            if used > limit:
                reason = "現在の予約送信上限に達しています。"
    if not reason and duplicate(db, delivery.recipient_email, delivery.id):
        reason = "同じ宛先の送信・結果不明が既にあります。"
    if reason:
        delivery.status, delivery.error_message = "blocked", reason
        delivery.finished_at, delivery.worker_id, delivery.lease_expires_at = (
            approval.now(),
            None,
            None,
        )
        approval.audit(db, item, "email blocked", "SYSTEM", None, item.status, "send guard denied")
        db.commit()
        return None
    attempt = EmailSendAttempt(
        reservation_id=row.id,
        payload_hash=item.payload_hash,
        payload_version=item.payload_version,
        message_id=f"<leadhive.{delivery.id}@{row.sender_email.rsplit('@', 1)[1]}>",
        started_at=approval.now(),
    )
    db.add(attempt)
    db.flush()  # Durable attempt evidence is required by the approval transition trigger.
    item.status = "CONSUMED"
    approval.audit(db, item, "dispatch reserved", "SYSTEM", None, "APPROVED")
    db.commit()  # Never contact SMTP before this transaction has committed.
    return attempt


def finish_attempt(db, delivery, result, message=""):
    row = reservation(db, delivery.id)
    item = db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.id == row.approval_id).with_for_update()
    )
    db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.id == delivery.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    attempt = db.scalar(
        select(EmailSendAttempt).where(EmailSendAttempt.reservation_id == row.id).with_for_update()
    )
    if not attempt or attempt.result != "STARTED":
        return
    attempt.result, attempt.finished_at = result, approval.now()
    delivery.status = {"SMTP_ACCEPTED": "sent", "FAILED": "failed", "UNKNOWN": "unknown"}[result]
    delivery.finished_at, delivery.worker_id, delivery.lease_expires_at = approval.now(), None, None
    delivery.error_message = message[:500]
    if result == "SMTP_ACCEPTED":
        delivery.sent_at = approval.now()
        legacy_approval = db.scalar(
            select(OutreachDraftApproval).where(
                OutreachDraftApproval.draft_id == delivery.draft_id,
                OutreachDraftApproval.approval_type == "email",
            )
        )
        if legacy_approval:
            legacy_approval.delivered_at = delivery.sent_at
        company = db.get(Company, delivery.company_id)
        if company and company.status in {"unreviewed", "target"}:
            company.status = "approached"
        from app.models import Activity

        db.add(
            Activity(
                company_id=delivery.company_id,
                activity_type="email",
                note="Human承認メール: SMTP受付済み（到達未確認）",
            )
        )
    approval.audit(db, item, "email result", "SYSTEM", None, item.status, result)
    db.commit()
