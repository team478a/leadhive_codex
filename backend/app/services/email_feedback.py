"""Deterministic circuit breaker. Never authorize or retry a send."""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.model_approved_email import ApprovedEmailBatch, ApprovedEmailReservation, EmailSendAttempt
from app.model_email_feedback import EmailFeedbackEvent, EmailHealthState
from app.models import Company, EmailDelivery, OutreachAuditEvent, Project, SuppressionEntry
from app.services import human_approval as approval


def state(db, project_id):
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    row = db.get(EmailHealthState, project_id)
    if row is None:
        row = EmailHealthState(project_id=project_id, paused=False, reason="")
        db.add(row)
        db.flush()
    return row


def metrics(db, project_id, reviewed_at=None):
    cutoff = approval.now() - timedelta(hours=24)
    if reviewed_at and reviewed_at > cutoff:
        cutoff = reviewed_at
    query = (
        select(EmailDelivery)
        .join(Company, Company.id == EmailDelivery.company_id)
        .where(Company.project_id == project_id, EmailDelivery.started_at >= cutoff)
    )
    attempted = db.scalar(select(func.count()).select_from(query.subquery()))
    unknown = db.scalar(
        select(func.count()).select_from(query.where(EmailDelivery.status == "unknown").subquery())
    )
    counts = dict(
        db.execute(
            select(
                EmailFeedbackEvent.kind, func.count(func.distinct(EmailFeedbackEvent.delivery_id))
            )
            .where(
                EmailFeedbackEvent.project_id == project_id,
                EmailFeedbackEvent.received_at >= cutoff,
            )
            .group_by(EmailFeedbackEvent.kind)
        ).all()
    )
    return {
        "attempted": attempted,
        "unknown": unknown,
        **{
            k: counts.get(k, 0)
            for k in ("delivered", "hard_bounce", "soft_bounce", "complaint", "unsubscribe")
        },
    }


def evaluate(db, project_id):
    row = state(db, project_id)
    counts = metrics(db, project_id, row.reviewed_at)
    reason = ""
    if counts["complaint"]:
        reason = "苦情を検出しました。送信内容・対象のHuman確認が必要です。"
    elif counts["unknown"] >= 3:
        reason = "24時間内の結果不明が3件以上です。SMTP履歴を確認してください。"
    elif (
        counts["hard_bounce"] >= 3
        and counts["attempted"] >= 10
        and counts["hard_bounce"] / counts["attempted"] >= 0.05
    ):
        reason = "不達が3件以上かつ送信試行の5%以上です。宛先リストを確認してください。"
    if reason and not row.paused:
        row.paused, row.reason, row.stopped_at = True, reason, approval.now()
        # Match reservation/execution lock order: Project -> reservation -> batch.
        db.execute(select(func.pg_advisory_xact_lock(4_781_002)))
        batches = db.scalars(
            select(ApprovedEmailBatch)
            .where(
                ApprovedEmailBatch.project_id == project_id, ApprovedEmailBatch.status == "queued"
            )
            .order_by(ApprovedEmailBatch.id)
            .with_for_update()
        ).all()
        for batch in batches:
            batch.status = "paused"
        db.add(
            OutreachAuditEvent(
                event="email health paused",
                principal_type="SYSTEM",
                project_id=project_id,
                reason=reason,
            )
        )
    return row, counts


def summary(db, project_id):
    row, counts = evaluate(db, project_id)
    return {
        "paused": row.paused,
        "reason": row.reason,
        "stopped_at": row.stopped_at,
        "reviewed_at": row.reviewed_at,
        "counts": counts,
    }


def refresh_pending(db):
    projects = db.scalars(
        select(ApprovedEmailBatch.project_id)
        .where(ApprovedEmailBatch.status == "queued")
        .distinct()
        .limit(100)
    ).all()
    for project_id in projects:
        evaluate(db, project_id)
        db.commit()


def record(db, body, source, actor=None, expected_project=None):
    delivery = db.get(EmailDelivery, body.delivery_id)
    company = db.get(Company, delivery.company_id) if delivery else None
    if not company or (expected_project and company.project_id != expected_project):
        raise HTTPException(404, "送信履歴が見つかりません。")
    state(db, company.project_id)
    old = db.scalar(
        select(EmailFeedbackEvent).where(
            EmailFeedbackEvent.source == source, EmailFeedbackEvent.event_key == body.event_key
        )
    )
    if old:
        if (old.delivery_id, old.kind, old.recipient, old.occurred_at) != (
            body.delivery_id,
            body.kind,
            body.recipient.strip().lower(),
            body.occurred_at,
        ):
            raise HTTPException(409, "同じ通知IDの内容が異なります。")
        if old.project_id != company.project_id:
            raise HTTPException(409, "通知IDが競合しています。")
        return old
    recipient = body.recipient.strip().lower()
    if recipient != delivery.recipient_email.strip().lower() or not delivery.started_at:
        raise HTTPException(409, "宛先または送信試行を確認できません。")
    if body.occurred_at < delivery.started_at or body.occurred_at > approval.now() + timedelta(
        minutes=5
    ):
        raise HTTPException(422, "通知日時が送信試行の範囲外です。")
    if source == "PROVIDER":
        attempt = db.scalar(
            select(EmailSendAttempt)
            .join(
                ApprovedEmailReservation,
                ApprovedEmailReservation.id == EmailSendAttempt.reservation_id,
            )
            .where(ApprovedEmailReservation.delivery_id == delivery.id)
        )
        if not attempt or body.message_id != attempt.message_id:
            raise HTTPException(409, "送信Message-IDが一致しません。")
    event = EmailFeedbackEvent(
        project_id=company.project_id,
        delivery_id=delivery.id,
        source=source,
        event_key=body.event_key,
        kind=body.kind,
        recipient=recipient,
        occurred_at=body.occurred_at,
        received_at=approval.now(),
        actor_user_id=actor.id if actor else None,
    )
    db.add(event)
    db.flush()
    if body.kind in {"hard_bounce", "complaint", "unsubscribe"}:
        if not db.scalar(
            select(SuppressionEntry.id).where(
                SuppressionEntry.project_id == company.project_id,
                func.lower(SuppressionEntry.email) == recipient,
            )
        ):
            db.add(
                SuppressionEntry(
                    project_id=company.project_id,
                    domain="",
                    email=recipient,
                    phone="",
                    reason=f"メール結果: {body.kind}",
                )
            )
        # Do not suppress an entire domain or unrelated phone because one address bounced.
        db.flush()
    db.add(
        OutreachAuditEvent(
            event="email feedback " + body.kind,
            principal_type="HUMAN" if actor else "SYSTEM",
            actor_id=actor.id if actor else None,
            project_id=company.project_id,
            company_id=company.id,
            reason=str(event.id),
        )
    )
    evaluate(db, company.project_id)
    return event
