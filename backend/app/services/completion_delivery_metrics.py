"""Read-only C2-linked Human approval and delivery evidence, scoped per cohort page."""

from uuid import UUID

from sqlalchemy import select

from app.models import (
    ApprovalRequest,
    ApprovedEmailReservation,
    ApprovedFormDispatch,
    EmailDelivery,
    EmailFeedbackEvent,
    EmailSendAttempt,
    FormDelivery,
    LeadDmPreparation,
    OutreachAuditEvent,
)
from app.services.dm_approval_preparation import BINDING
from app.services.human_approval import payload_hash

RESULTS = ("ACCEPTED", "DELIVERED", "UNKNOWN", "FAILED", "IN_PROGRESS")


def empty():
    return dict(
        prepared_ever=False,
        human_approved=False,
        sent=False,
        attempt_count=0,
        results={key: 0 for key in RESULTS},
        queued=0,
        blocked=0,
        cancelled=0,
        preflight_failed=0,
        unverified_records=0,
    )


def page_history(db, project_id, company_ids):
    output = {company_id: empty() for company_id in company_ids}
    requests = list(
        db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.project_id == project_id,
                ApprovalRequest.company_id.in_(company_ids),
                ApprovalRequest.payload_snapshot.has_key(BINDING),
            )
        )
    )
    valid = {}
    for request in requests:
        binding = request.payload_snapshot.get(BINDING, {})
        try:
            source = db.get(LeadDmPreparation, UUID(str(binding["preparation_id"])))
        except (KeyError, TypeError, ValueError):
            source = None
        if (
            source
            and source.company_id == request.company_id
            and source.project_id == project_id
            and binding.get("version") == "lead-dm-c2-v1"
            and binding.get("source_snapshot_hash") == payload_hash(source.snapshot)
            and binding.get("choice_version") == source.choice_version
            and binding.get("evidence") == source.snapshot.get("evidence")
            and request.body == source.snapshot.get("body")
            and request.subject == source.snapshot.get("subject")
            and request.channel == source.snapshot.get("destination", {}).get("type")
            and payload_hash(request.payload_snapshot) == request.payload_hash
        ):
            valid[request.id] = request
    for request in requests:
        row = output[request.company_id]
        if request.id in valid:
            row["prepared_ever"] = True
        else:
            row["unverified_records"] += 1
    if not valid:
        return output
    approved = set()
    for event in db.scalars(
        select(OutreachAuditEvent).where(
            OutreachAuditEvent.project_id == project_id,
            OutreachAuditEvent.request_id.in_(valid),
            OutreachAuditEvent.event == "approval granted",
            OutreachAuditEvent.principal_type == "HUMAN",
        )
    ):
        request = valid[event.request_id]
        if (
            event.company_id == request.company_id
            and event.actor_id is not None
            and event.actor_id == request.approved_by_user_id
            and event.payload_hash == request.approved_payload_hash == request.payload_hash
            and event.payload_version == request.approved_payload_version == request.payload_version
            and request.approved_at is not None
        ):
            approved.add(request.id)
            output[request.company_id]["human_approved"] = True
    if not approved:
        return output
    email_rows = db.execute(
        select(ApprovedEmailReservation, EmailDelivery, EmailSendAttempt)
        .join(EmailDelivery, EmailDelivery.id == ApprovedEmailReservation.delivery_id)
        .outerjoin(EmailSendAttempt, EmailSendAttempt.reservation_id == ApprovedEmailReservation.id)
        .where(ApprovedEmailReservation.approval_id.in_(approved))
    ).all()
    delivery_ids = [d.id for _, d, _ in email_rows]
    feedback = {}
    if delivery_ids:
        for event in db.scalars(
            select(EmailFeedbackEvent)
            .where(
                EmailFeedbackEvent.project_id == project_id,
                EmailFeedbackEvent.delivery_id.in_(delivery_ids),
                EmailFeedbackEvent.kind.in_(("delivered", "hard_bounce", "soft_bounce")),
            )
            .order_by(
                EmailFeedbackEvent.occurred_at,
                EmailFeedbackEvent.received_at,
                EmailFeedbackEvent.id,
            )
        ):
            feedback[event.delivery_id] = event
    for reservation, delivery, attempt in email_rows:
        request = valid[reservation.approval_id]
        row = output[request.company_id]
        if (
            delivery.company_id != request.company_id
            or request.channel != "email"
            or payload_hash(reservation.envelope) != reservation.envelope_hash
            or reservation.envelope.get("approval_hash") != request.payload_hash
            or reservation.envelope.get("approval_version") != request.payload_version
            or reservation.envelope.get("company_id") != str(request.company_id)
            or delivery.recipient_email.casefold() != (request.recipient or "").casefold()
        ):
            row["unverified_records"] += 1
            continue
        if attempt is None:
            waiting(row, delivery.status)
            continue
        if (
            attempt.payload_hash != request.payload_hash
            or attempt.payload_version != request.payload_version
        ):
            row["unverified_records"] += 1
            continue
        event = feedback.get(delivery.id)
        if event and event.recipient.casefold() != delivery.recipient_email.casefold():
            event = None
        record(row, email_result(attempt, delivery, event))
    for dispatch, delivery in db.execute(
        select(ApprovedFormDispatch, FormDelivery)
        .outerjoin(FormDelivery, FormDelivery.id == ApprovedFormDispatch.delivery_id)
        .where(
            ApprovedFormDispatch.project_id == project_id,
            ApprovedFormDispatch.approval_id.in_(approved),
        )
    ):
        request = valid[dispatch.approval_id]
        row = output[request.company_id]
        if (
            dispatch.company_id != request.company_id
            or request.channel != "form"
            or dispatch.payload_hash != request.payload_hash
            or payload_hash(dispatch.payload_snapshot) != dispatch.payload_hash
        ):
            row["unverified_records"] += 1
            continue
        if dispatch.started_at is None:
            waiting(row, dispatch.status)
            continue
        if (
            not delivery
            or delivery.company_id != request.company_id
            or delivery.draft_id != dispatch.draft_id
        ):
            row["unverified_records"] += 1
            continue
        if dispatch.status == "unknown" or delivery.status == "unknown":
            result = "UNKNOWN"
        elif (
            dispatch.status == "submitted"
            and delivery.status == "submitted"
            and delivery.submitted_at
        ):
            result = "ACCEPTED"
        elif dispatch.status == "failed" and delivery.status == "failed":
            result = "FAILED"
        elif dispatch.status == "checking" and delivery.status == "pending":
            result = "IN_PROGRESS"
        else:
            result = "UNKNOWN"
            row["unverified_records"] += 1
        record(row, result)
    return output


def waiting(row, status):
    key = {
        "queued": "queued",
        "running": "queued",
        "checking": "queued",
        "blocked": "blocked",
        "cancelled": "cancelled",
        "failed": "preflight_failed",
    }.get(status)
    if key:
        row[key] += 1
    else:
        row["unverified_records"] += 1


def record(row, result):
    row["sent"] = True
    row["attempt_count"] += 1
    row["results"][result] += 1


def email_result(attempt, delivery, feedback=None):
    result = {
        "SMTP_ACCEPTED": "ACCEPTED",
        "FAILED": "FAILED",
        "UNKNOWN": "UNKNOWN",
        "STARTED": "IN_PROGRESS",
    }[attempt.result]
    if result == "IN_PROGRESS" and delivery.status == "unknown":
        return "UNKNOWN"
    if result == "ACCEPTED" and feedback:
        return {"delivered": "DELIVERED", "hard_bounce": "FAILED", "soft_bounce": "UNKNOWN"}[
            feedback.kind
        ]
    return result
