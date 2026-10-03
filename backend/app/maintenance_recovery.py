"""Invalidate restored authorization, preserving immutable payloads and append-only history."""

from sqlalchemy import func, select, update

from app.models import (
    AgentCredential,
    ApprovalRequest,
    AuthSession,
    HumanApprovalProof,
    OutreachAuditEvent,
)


def invalidate_restored_authorizations(connection) -> dict:
    counts = {}
    for model in (AuthSession, HumanApprovalProof):
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
    connection.execute(
        OutreachAuditEvent.__table__.insert().values(
            event="recovery_auth_invalidated",
            principal_type="SYSTEM",
            reason="Restored sessions, challenges and agent credentials invalidated.",
        )
    )
    return counts
