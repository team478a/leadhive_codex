"""Synthetic stored history only: no dispatch endpoint, worker or external connection."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.models import ApprovalRequest, ApprovedFormDispatch, FormDelivery, Project
from app.services.completion_delivery_metrics import email_result, page_history
from tests.test_approval_foundation import approve, challenge, expected
from tests.test_dm_approval_preparation import pending, prepared


def approved_source(auth, db):
    company, profile, path, _, _ = prepared(auth, db)
    item, _ = pending(auth, path)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    return company, profile, db.get(ApprovalRequest, UUID(item["id"]))


def history(db, company):
    return page_history(db, company.project_id, [company.id])[company.id]


def test_approval_history_survives_revoke_but_never_counts_unsent(auth, db):
    company, _, request = approved_source(auth, db)
    result = history(db, company)
    assert result["prepared_ever"] and result["human_approved"]
    assert not result["sent"] and result["attempt_count"] == 0
    response = auth.post(
        f"/api/approval-requests/{request.id}/revoke",
        json=expected(
            {"payload_hash": request.payload_hash, "payload_version": request.payload_version}
        )
        | {"reason": "Synthetic review"},
    )
    assert response.status_code == 200, response.text
    assert history(db, company)["human_approved"]
    assert db.get(ApprovalRequest, request.id).status == "REVOKED"


@pytest.mark.parametrize(
    "status,started,result_key",
    [
        ("queued", False, "queued"),
        ("blocked", False, "blocked"),
        ("failed", False, "preflight_failed"),
        ("cancelled", False, "cancelled"),
        ("submitted", True, "ACCEPTED"),
        ("unknown", True, "UNKNOWN"),
        ("failed", True, "FAILED"),
    ],
)
def test_stored_form_results_and_reservations_are_distinct(auth, db, status, started, result_key):
    company, profile, request = approved_source(auth, db)
    now = datetime.now(timezone.utc)
    delivery = None
    if started:
        delivery = FormDelivery(
            draft_id=request.source_draft_id,
            company_id=company.id,
            form_profile_id=profile.id,
            form_url=profile.form_url,
            action_url=profile.action_url,
            status=status,
            submitted_at=now if status == "submitted" else None,
            completion_evidence="Synthetic acceptance" if status == "submitted" else "",
        )
        db.add(delivery)
        db.flush()
    db.add(
        ApprovedFormDispatch(
            approval_id=request.id,
            project_id=request.project_id,
            company_id=company.id,
            draft_id=request.source_draft_id,
            created_by_user_id=request.approved_by_user_id,
            idempotency_key=uuid4(),
            request_hash="a" * 64,
            payload_snapshot=request.payload_snapshot,
            payload_hash=request.payload_hash,
            form_url=profile.form_url,
            status=status,
            started_at=now if started else None,
            delivery_id=delivery.id if delivery else None,
        )
    )
    db.commit()
    result = history(db, company)
    assert result["sent"] == started
    assert result["attempt_count"] == int(started)
    assert (result["results"][result_key] if started else result[result_key]) == 1
    assert sum(result["results"].values()) == int(started)
    assert result["results"]["DELIVERED"] == 0
    assert db.get(ApprovalRequest, request.id).status == "APPROVED"


def test_pending_and_other_project_are_not_human_approved(auth, db):
    company, _, path, _, _ = prepared(auth, db)
    pending(auth, path)
    result = history(db, company)
    assert result["prepared_ever"] and not result["human_approved"]
    assert page_history(db, uuid4(), [company.id])[company.id]["prepared_ever"] is False
    cohort = auth.post(
        f"/api/projects/{company.project_id}/completion-cohorts", json={"name": "Synthetic C3"}
    ).json()
    endpoint = f"/api/completion-cohorts/{cohort['id']}/destination-diagnostics"
    response = auth.get(endpoint)
    assert response.status_code == 200
    assert response.json()["rows"][0]["delivery_funnel"] == result
    assert auth.get(endpoint, headers={"Authorization": "Bearer agent"}).status_code == 403


@pytest.mark.parametrize(
    "transport,status,feedback,wanted",
    [
        ("SMTP_ACCEPTED", "sent", None, "ACCEPTED"),
        ("SMTP_ACCEPTED", "sent", "delivered", "DELIVERED"),
        ("SMTP_ACCEPTED", "sent", "hard_bounce", "FAILED"),
        ("SMTP_ACCEPTED", "sent", "soft_bounce", "UNKNOWN"),
        ("UNKNOWN", "unknown", "delivered", "UNKNOWN"),
        ("STARTED", "running", None, "IN_PROGRESS"),
        ("STARTED", "unknown", None, "UNKNOWN"),
        ("FAILED", "failed", None, "FAILED"),
    ],
)
def test_email_acceptance_and_delivery_evidence_are_distinct(transport, status, feedback, wanted):
    assert (
        email_result(
            SimpleNamespace(result=transport),
            SimpleNamespace(status=status),
            SimpleNamespace(kind=feedback) if feedback else None,
        )
        == wanted
    )


@pytest.mark.parametrize(
    "result,receipt,wanted",
    [
        ("SMTP_ACCEPTED", None, "ACCEPTED"),
        ("SMTP_ACCEPTED", "delivered", "DELIVERED"),
        ("SMTP_ACCEPTED", "hard_bounce", "FAILED"),
        ("UNKNOWN", "delivered", "UNKNOWN"),
    ],
)
def test_linked_email_evidence_and_feedback(auth, db, monkeypatch, result, receipt, wanted):
    from app.config import settings
    from app.models import (
        ApprovedEmailBatch,
        ApprovedEmailReservation,
        EmailDelivery,
        EmailFeedbackEvent,
        EmailSendAttempt,
    )
    from app.services.human_approval import payload_hash

    monkeypatch.setattr(settings, "smtp_from_name", "Synthetic sender")
    monkeypatch.setattr(settings, "smtp_from_email", "sender@example.com")
    company, _, path, _, _ = prepared(auth, db, channel="email")
    item, _ = pending(auth, path)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    request = db.get(ApprovalRequest, UUID(item["id"]))
    now = datetime.now(timezone.utc)
    delivery = EmailDelivery(
        draft_id=request.source_draft_id,
        company_id=company.id,
        recipient_email=request.recipient,
        subject=request.subject,
        body=request.body,
        scheduled_for=now,
        confirmed_at=request.approved_at,
        status="sent" if result == "SMTP_ACCEPTED" else "unknown",
    )
    batch = ApprovedEmailBatch(
        project_id=company.project_id,
        created_by_user_id=request.approved_by_user_id,
        idempotency_key=uuid4(),
        request_hash="a" * 64,
        name="Synthetic only",
    )
    db.add_all([delivery, batch])
    db.flush()
    envelope = dict(
        approval_hash=request.payload_hash,
        approval_version=request.payload_version,
        company_id=str(company.id),
    )
    reservation = ApprovedEmailReservation(
        batch_id=batch.id,
        approval_id=request.id,
        delivery_id=delivery.id,
        envelope=envelope,
        envelope_hash=payload_hash(envelope),
        sender_email="sender@example.com",
        recipient_email=request.recipient,
    )
    db.add(reservation)
    db.flush()
    db.add(
        EmailSendAttempt(
            reservation_id=reservation.id,
            payload_hash=request.payload_hash,
            payload_version=request.payload_version,
            message_id=str(uuid4()),
            result=result,
            started_at=now,
            finished_at=now,
        )
    )
    if receipt:
        db.add(
            EmailFeedbackEvent(
                project_id=company.project_id,
                delivery_id=delivery.id,
                source="HUMAN",
                event_key=str(uuid4()),
                kind=receipt,
                recipient=request.recipient,
                occurred_at=now,
                actor_user_id=request.approved_by_user_id,
            )
        )
    db.commit()
    before = request.status
    measured = history(db, company)
    assert measured["sent"] and measured["attempt_count"] == 1
    assert measured["results"][wanted] == 1
    assert measured["unverified_records"] == 0
    assert db.get(ApprovalRequest, request.id).status == before


def test_unbound_legacy_approval_is_not_c2_history(auth, db):
    company, _, _, _, _ = prepared(auth, db)
    from tests.test_approval_foundation import create

    project = db.get(Project, company.project_id)
    item = create(auth, (project, company))
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    measured = history(db, company)
    assert not measured["prepared_ever"] and not measured["human_approved"]
    assert not measured["sent"]


def test_unverified_dispatch_is_not_a_success(auth, db):
    company, profile, request = approved_source(auth, db)
    now = datetime.now(timezone.utc)
    delivery = FormDelivery(
        draft_id=request.source_draft_id,
        company_id=company.id,
        form_url=profile.form_url,
        status="submitted",
        submitted_at=now,
    )
    db.add(delivery)
    db.flush()
    db.add(
        ApprovedFormDispatch(
            approval_id=request.id,
            project_id=request.project_id,
            company_id=company.id,
            draft_id=request.source_draft_id,
            created_by_user_id=request.approved_by_user_id,
            idempotency_key=uuid4(),
            request_hash="a" * 64,
            payload_snapshot=request.payload_snapshot,
            payload_hash="f" * 64,
            form_url=profile.form_url,
            status="submitted",
            started_at=now,
            delivery_id=delivery.id,
        )
    )
    db.commit()
    measured = history(db, company)
    assert measured["unverified_records"] == 1
    assert not measured["sent"] and measured["results"]["ACCEPTED"] == 0


def test_system_event_cannot_replace_human_approval(auth, db):
    from app.models import OutreachAuditEvent

    company, _, path, _, _ = prepared(auth, db)
    item, _ = pending(auth, path)
    request = db.get(ApprovalRequest, UUID(item["id"]))
    db.add(
        OutreachAuditEvent(
            event="approval granted",
            principal_type="SYSTEM",
            request_id=request.id,
            company_id=company.id,
            project_id=company.project_id,
            payload_hash=request.payload_hash,
            payload_version=request.payload_version,
            after_status="APPROVED",
        )
    )
    db.commit()
    assert history(db, company)["prepared_ever"]
    assert not history(db, company)["human_approved"]
    assert db.get(ApprovalRequest, request.id).status == "PENDING"
