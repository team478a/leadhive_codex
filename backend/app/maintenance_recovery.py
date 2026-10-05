"""Invalidate restored authorization, preserving immutable payloads and append-only history."""

from sqlalchemy import func, select, update

from app.model_approved_email import ApprovedEmailReservation, BulkApprovalProof, EmailSendAttempt
from app.models import (
    AgentCredential,
    ApprovalRequest,
    AuthSession,
    EmailDelivery,
    HumanApprovalProof,
    OutreachAuditEvent,
)


def invalidate_restored_authorizations(connection) -> dict:
    counts = {}
    for model in (AuthSession, HumanApprovalProof, BulkApprovalProof):
        result = connection.execute(
            update(model.__table__)
            .where(model.expires_at > func.now())
            .values(expires_at=func.now())
        )
        counts[model.__tablename__] = result.rowcount
    result = connection.execute(
        update(AgentCredential.__table__)
        .where(AgentCredential.revoked.is_(False))
        .values(revoked=True)
    )
    counts["agent_credentials"] = result.rowcount
    columns = (
        ApprovalRequest.id,
        ApprovalRequest.project_id,
        ApprovalRequest.company_id,
        ApprovalRequest.payload_hash,
        ApprovalRequest.payload_version,
        ApprovalRequest.status,
    )
    requests = (
        connection.execute(
            select(*columns)
            .where(ApprovalRequest.status.in_(("PENDING", "APPROVED")))
            .with_for_update()
        )
        .mappings()
        .all()
    )
    for request in requests:
        connection.execute(
            update(ApprovalRequest.__table__)
            .where(ApprovalRequest.id == request["id"])
            .values(status="REVOKED", invalidation_reason="restored_requires_reapproval")
        )
        connection.execute(
            OutreachAuditEvent.__table__.insert().values(
                event="restored_approval_revoked",
                principal_type="SYSTEM",
                request_id=request["id"],
                project_id=request["project_id"],
                company_id=request["company_id"],
                payload_hash=request["payload_hash"],
                payload_version=request["payload_version"],
                before_status=request["status"],
                after_status="REVOKED",
                reason="Restored authorization requires renewed human approval.",
            )
        )
    counts["approval_requests"] = len(requests)
    attempts = (
        connection.execute(
            select(
                EmailSendAttempt.id.label("attempt_id"),
                ApprovedEmailReservation.delivery_id,
                ApprovalRequest.id.label("approval_id"),
                *columns[1:],
            )
            .select_from(EmailSendAttempt)
            .join(
                ApprovedEmailReservation,
                ApprovedEmailReservation.id == EmailSendAttempt.reservation_id,
            )
            .join(ApprovalRequest, ApprovalRequest.id == ApprovedEmailReservation.approval_id)
            .where(EmailSendAttempt.result == "STARTED")
        )
        .mappings()
        .all()
    )
    for attempt in attempts:
        connection.execute(
            update(EmailSendAttempt.__table__)
            .where(EmailSendAttempt.id == attempt["attempt_id"])
            .values(result="UNKNOWN", finished_at=func.now())
        )
        connection.execute(
            update(EmailDelivery.__table__)
            .where(EmailDelivery.id == attempt["delivery_id"])
            .values(
                status="unknown",
                worker_id=None,
                lease_expires_at=None,
                finished_at=func.now(),
                error_message="復元した送信試行は結果不明です。再送せずSMTP履歴を確認してください。",
            )
        )
        connection.execute(
            OutreachAuditEvent.__table__.insert().values(
                event="restored_email_unknown",
                principal_type="SYSTEM",
                request_id=attempt["approval_id"],
                project_id=attempt["project_id"],
                company_id=attempt["company_id"],
                payload_hash=attempt["payload_hash"],
                payload_version=attempt["payload_version"],
                before_status="CONSUMED",
                after_status="CONSUMED",
                reason="Restored SMTP attempt requires human review.",
            )
        )
    counts["email_attempts_unknown"] = len(attempts)
    connection.execute(
        OutreachAuditEvent.__table__.insert().values(
            event="recovery_auth_invalidated",
            principal_type="SYSTEM",
            reason="Restored sessions, challenges and agent credentials invalidated.",
        )
    )
    return counts
