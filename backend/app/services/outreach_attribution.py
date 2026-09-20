from datetime import datetime, timezone

from sqlalchemy import select

from app.models import (
    Company,
    InboundEmail,
    OutreachConversion,
    OutreachDraft,
    OutreachDraftApproval,
)


def latest_eligible_approval(
    db, company_id, occurred_at: datetime
) -> OutreachDraftApproval | None:
    return db.scalar(
        select(OutreachDraftApproval)
        .join(OutreachDraft, OutreachDraft.id == OutreachDraftApproval.draft_id)
        .where(
            OutreachDraft.company_id == company_id,
            OutreachDraftApproval.approved_at <= occurred_at,
        )
        .order_by(OutreachDraftApproval.approved_at.desc(), OutreachDraftApproval.id.desc())
        .limit(1)
    )


def attribute_inbound_reply(
    db, inbound: InboundEmail, company: Company
) -> OutreachDraftApproval | None:
    if inbound.classification != "reply":
        return None
    approval = latest_eligible_approval(db, company.id, inbound.received_at)
    if approval is None:
        return None
    inbound.outreach_approval_id = approval.id
    db.add(
        OutreachConversion(
            approval_id=approval.id,
            company_id=company.id,
            inbound_email_id=inbound.id,
            outcome="replied",
            occurred_at=inbound.received_at,
        )
    )
    return approval


def record_outreach_conversion(
    db,
    approval: OutreachDraftApproval,
    company: Company,
    outcome: str,
    *,
    inbound_email: InboundEmail | None = None,
    occurred_at: datetime | None = None,
) -> None:
    db.add(
        OutreachConversion(
            approval_id=approval.id,
            company_id=company.id,
            inbound_email_id=inbound_email.id if inbound_email else None,
            outcome=outcome,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
    )
