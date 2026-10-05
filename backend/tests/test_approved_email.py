"""Human dispatch boundary, real PostgreSQL and simulated SMTP only."""

import smtplib
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.model_approved_email import BulkApprovalProof, EmailSendAttempt
from app.models import ApprovalRequest, EmailDelivery, ProjectMember, SuppressionEntry
from app.services import approved_email, approved_email_worker, human_approval
from app.services.email_delivery import (
    EmailDeliveryError,
    SmtpConfiguration,
    send_with_configuration,
)
from tests import test_approval_foundation as foundation
from tests.conftest import PASSWORD
from tests.test_approval_foundation import create


@pytest.fixture
def approval_workspace(db, users):
    return foundation.workspace.__wrapped__(db, users)


@pytest.fixture
def configured(monkeypatch, approval_workspace):
    monkeypatch.setattr(settings, "human_approved_email_enabled", True)
    monkeypatch.setattr(settings, "smtp_from_email", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_from_name", "Human")
    monkeypatch.setattr(settings, "smtp_host", "never-connect.invalid")
    monkeypatch.setattr(settings, "smtp_minimum_interval_seconds", 0)
    monkeypatch.setattr(settings, "public_app_url", "https://leadhive.example")
    approval_workspace[1].email = "recipient@example.com"
    return approval_workspace


def selection(item):
    return {
        "request_id": item["id"],
        "expected_hash": item["payload_hash"],
        "expected_version": item["payload_version"],
    }


def proof(auth, project, items, verify=True):
    prefix = f"/api/projects/{project.id}/bulk-approval"
    response = auth.post(prefix + "/challenge", json={"items": [selection(i) for i in items]})
    assert response.status_code == 200, response.text
    token = response.json()["challenge_token"]
    if verify:
        response = auth.post(
            prefix + "/verify", json={"challenge_token": token, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
    return token


def approved(auth, configured):
    item = create(auth, configured)
    token = proof(auth, configured[0], [item])
    result = auth.post(
        f"/api/projects/{configured[0].id}/bulk-approval/approve", json={"challenge_token": token}
    )
    assert result.status_code == 200, result.text
    return item


def queue(auth, configured, item, **overrides):
    body = {
        "items": [selection(item)],
        "name": "Approved batch",
        "idempotency_key": str(uuid4()),
        **overrides,
    }
    response = auth.post(f"/api/projects/{configured[0].id}/approved-email-batches", json=body)
    return response, body


def delivery(db):
    return db.scalar(select(EmailDelivery))


def test_bulk_stepup_replay_and_agent_denial(auth, db, configured):
    item = create(auth, configured)
    prefix = f"/api/projects/{configured[0].id}/bulk-approval"
    token = proof(auth, configured[0], [item], verify=False)
    assert auth.post(prefix + "/approve", json={"challenge_token": token}).status_code == 403
    assert (
        auth.post(
            prefix + "/verify", json={"challenge_token": token, "password": PASSWORD}
        ).status_code
        == 200
    )
    assert auth.post(prefix + "/approve", json={"challenge_token": token}).status_code == 200
    assert auth.post(prefix + "/approve", json={"challenge_token": token}).status_code == 403
    assert (
        auth.post(
            prefix + "/approve",
            headers={"Authorization": "Bearer lh_agent_fake"},
            json={"challenge_token": token, "confirmed": True},
        ).status_code
        == 403
    )
    assert db.get(ApprovalRequest, UUID(item["id"])).approved_by_user_id is not None


@pytest.mark.parametrize("invalid", ["expiry", "hash", "version", "viewer"])
def test_bulk_invalid_conditions(auth, db, configured, users, monkeypatch, invalid):
    item = create(auth, configured)
    token = proof(auth, configured[0], [item])
    stored = db.scalar(select(BulkApprovalProof))
    if invalid == "expiry":
        stored.expires_at = human_approval.now() - timedelta(seconds=1)
    elif invalid in {"hash", "version"}:
        changed = [dict(i) for i in stored.items]
        changed[0]["expected_" + invalid] = "0" * 64 if invalid == "hash" else 99
        stored.items = changed
    else:
        configured[0].user_id = users[1].id
        db.add(ProjectMember(project_id=configured[0].id, user_id=users[0].id, role="viewer"))
    db.commit()
    response = auth.post(
        f"/api/projects/{configured[0].id}/bulk-approval/approve", json={"challenge_token": token}
    )
    assert response.status_code in {403, 404, 409}
    assert db.get(ApprovalRequest, UUID(item["id"])).status == "PENDING"


def test_reservation_idempotency_and_no_dispatch(auth, db, configured, monkeypatch):
    item = approved(auth, configured)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    result, body = queue(auth, configured, item)
    assert result.status_code == 201, result.text
    assert not result.json()["execution_enabled"]
    again = auth.post(f"/api/projects/{configured[0].id}/approved-email-batches", json=body)
    assert again.json()["id"] == result.json()["id"]
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 1
    assert approved_email_worker.claim(db) is None
    assert db.get(ApprovalRequest, UUID(item["id"])).status == "APPROVED"
    assert queue(auth, configured, item)[0].status_code == 409


@pytest.mark.parametrize(
    "change", ["suppression", "company", "sender", "revoke", "expiry", "tamper"]
)
def test_send_guards_recheck_after_queue(auth, db, configured, monkeypatch, change):
    item = approved(auth, configured)
    response, _ = queue(auth, configured, item)
    assert response.status_code == 201, response.text
    request = db.get(ApprovalRequest, UUID(item["id"]))
    if change == "expiry":
        monkeypatch.setattr(
            human_approval, "now", lambda: request.expires_at - timedelta(seconds=1)
        )
    job = approved_email_worker.claim(db)
    assert job
    if change == "suppression":
        db.add(
            SuppressionEntry(
                project_id=configured[0].id, email="recipient@example.com", reason="opt-out"
            )
        )
    elif change == "company":
        configured[1].company_name = "Changed company"
    elif change == "sender":
        monkeypatch.setattr(settings, "smtp_from_email", "changed@example.com")
    elif change == "revoke":
        request.status = "REVOKED"
    elif change == "expiry":
        monkeypatch.setattr(
            human_approval, "now", lambda: request.expires_at + timedelta(seconds=1)
        )
    else:
        job.body = "tampered"
    db.commit()
    monkeypatch.setattr(
        approved_email_worker,
        "send_with_configuration",
        lambda *a, **k: pytest.fail("guard allowed SMTP"),
    )
    approved_email_worker.run(db, job)
    assert job.status == "blocked"
    assert db.scalar(select(func.count()).select_from(EmailSendAttempt)) == 0


@pytest.mark.parametrize("result", ["accepted", "unknown", "failed"])
def test_durable_attempt_and_results(auth, db, configured, monkeypatch, result):
    item = approved(auth, configured)
    assert queue(auth, configured, item)[0].status_code == 201
    job = approved_email_worker.claim(db)

    def smtp(config, message_id, recipient, subject, body, **kwargs):
        assert db.get(ApprovalRequest, UUID(item["id"])).status == "CONSUMED"
        assert db.scalar(select(EmailSendAttempt)).result == "STARTED"
        assert body == item["body"]
        assert kwargs["stable_message_id"] == f"<leadhive.{job.id}@example.com>"
        assert kwargs["unsubscribe_url"].startswith(
            "https://leadhive.example/api/public/unsubscribe/"
        )
        if result != "accepted":
            raise EmailDeliveryError("simulated", unknown=result == "unknown")

    monkeypatch.setattr(approved_email_worker, "send_with_configuration", smtp)
    approved_email_worker.run(db, job)
    assert job.status == {"accepted": "sent", "unknown": "unknown", "failed": "failed"}[result]
    assert (
        auth.post(f"/api/email-deliveries/{job.id}/retry", json={"confirmed": True}).status_code
        == 409
    )
    assert approved_email_worker.claim(db) is None


def test_worker_recovery_unknown_never_retry(auth, db, configured):
    item = approved(auth, configured)
    assert queue(auth, configured, item)[0].status_code == 201
    job = approved_email_worker.claim(db)
    assert approved_email.begin_attempt(db, job)
    assert approved_email.begin_attempt(db, job) is None
    assert job.status == "running"
    job.lease_expires_at = human_approval.now() - timedelta(seconds=1)
    db.commit()
    from app.worker import recover_stale_email_deliveries

    assert recover_stale_email_deliveries(db) == 1
    assert job.status == "unknown"
    assert approved_email_worker.claim(db) is None
    assert db.scalar(select(EmailSendAttempt)).result == "UNKNOWN"


def test_reservation_immutable_and_consume_requires_evidence(auth, db, configured):
    item = approved(auth, configured)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text("UPDATE approval_requests SET status='CONSUMED'"))
    assert queue(auth, configured, item)[0].status_code == 201
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text("UPDATE approved_email_reservations SET envelope_hash='tamper'"))


def test_pause_resume_cancel(auth, db, configured):
    item = approved(auth, configured)
    response, _ = queue(auth, configured, item)
    batch_id = response.json()["id"]
    prefix = f"/api/approved-email-batches/{batch_id}"
    assert auth.post(prefix + "/pause").status_code == 200
    assert approved_email_worker.claim(db) is None
    assert auth.post(prefix + "/resume").status_code == 200
    assert auth.post(prefix + "/cancel").status_code == 200
    assert delivery(db).status == "cancelled"


def test_pending_cannot_reserve_or_legacy_confirm(auth, db, configured):
    item = create(auth, configured)
    assert queue(auth, configured, item)[0].status_code == 409
    from app.models import OutreachDraft

    draft = OutreachDraft(company_id=configured[1].id, channel="email", subject="test", body="body")
    db.add(draft)
    db.commit()
    response = auth.post(
        f"/api/outreach-drafts/{draft.id}/email-delivery",
        json={"confirmed": True, "recipient_email": "recipient@example.com"},
    )
    assert response.status_code == 409
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0


def test_limits_and_unknown_duplicate_across_proposals(auth, db, configured, monkeypatch):
    item = approved(auth, configured)
    assert queue(auth, configured, item, daily_limit=1, hourly_limit=1)[0].status_code == 201
    job = approved_email_worker.claim(db)
    monkeypatch.setattr(
        approved_email_worker,
        "send_with_configuration",
        lambda *a, **k: (_ for _ in ()).throw(EmailDeliveryError("uncertain", unknown=True)),
    )
    approved_email_worker.run(db, job)
    new = approved(auth, configured)
    assert queue(auth, configured, new)[0].status_code == 409
    assert job.status == "unknown"


def test_quota_and_other_projects(auth, db, configured, users, monkeypatch):
    from app.models import Company

    first = approved(auth, configured)
    second_company = Company(
        project_id=configured[0].id,
        source="url",
        company_name="Second",
        email="second@example.com",
        domain="second.example",
        website_url="https://second.example",
    )
    db.add(second_company)
    db.commit()
    second = create(auth, (configured[0], second_company), recipient="second@example.com")
    token = proof(auth, configured[0], [second])
    assert (
        auth.post(
            f"/api/projects/{configured[0].id}/bulk-approval/approve",
            json={"challenge_token": token},
        ).status_code
        == 200
    )
    response, _ = queue(
        auth,
        configured,
        first,
        items=[selection(first), selection(second)],
        daily_limit=1,
        hourly_limit=1,
    )
    assert response.status_code == 201, response.text
    job = approved_email_worker.claim(db)
    assert job
    assert approved_email_worker.claim(db) is None
    # Another project/request ID cannot be introduced through a confirmation boolean.
    assert (
        auth.post(
            f"/api/projects/{uuid4()}/bulk-approval/challenge", json={"items": [selection(first)]}
        ).status_code
        == 404
    )


def test_bulk_atomic_invalidation(auth, db, configured):
    from app.models import Company

    first = create(auth, configured)
    second_company = Company(
        project_id=configured[0].id,
        source="url",
        company_name="Second",
        email="second@example.com",
        domain="second.example",
        website_url="https://second.example",
    )
    db.add(second_company)
    db.commit()
    second = create(auth, (configured[0], second_company), recipient="second@example.com")
    token = proof(auth, configured[0], [first, second])
    second_company.company_name = "Changed"
    db.commit()
    result = auth.post(
        f"/api/projects/{configured[0].id}/bulk-approval/approve", json={"challenge_token": token}
    )
    assert result.status_code == 409
    assert db.get(ApprovalRequest, UUID(first["id"])).status == "PENDING"
    assert db.get(ApprovalRequest, UUID(second["id"])).status == "REVOKED"


def test_unsubscribe_confirmation_no_scanner_mutation(auth, db, configured):
    item = approved(auth, configured)
    assert queue(auth, configured, item)[0].status_code == 201
    path = f"/api/public/unsubscribe/{delivery(db).unsubscribe_token}"
    assert auth.get(path).status_code == 200
    assert not configured[1].do_not_contact
    assert auth.post(path, headers={"Origin": "https://leadhive.example"}).status_code == 200
    assert configured[1].do_not_contact
    assert db.scalar(select(SuppressionEntry)).email == "recipient@example.com"


def test_restore_burns_bulk_proof_and_preserves_unknown(auth, db, configured):
    item = approved(auth, configured)
    assert queue(auth, configured, item)[0].status_code == 201
    job = approved_email_worker.claim(db)
    assert approved_email.begin_attempt(db, job)
    from app.maintenance_recovery import invalidate_restored_authorizations

    report = invalidate_restored_authorizations(db.connection())
    db.expire_all()
    assert report["email_attempts_unknown"] == 1
    assert job.status == "unknown"
    assert db.scalar(select(EmailSendAttempt)).result == "UNKNOWN"
    assert db.scalar(select(BulkApprovalProof)).expires_at <= human_approval.now()


def test_prepare_existing_draft_and_repropose_after_revocation(auth, db, configured):
    from app.models import OutreachDraft

    draft = OutreachDraft(
        company_id=configured[1].id, channel="email", subject="Draft subject", body="Draft body"
    )
    db.add(draft)
    db.commit()
    prefix = f"/api/projects/{configured[0].id}"
    assert auth.get(prefix + "/approval-email-drafts").json()[0]["id"] == str(draft.id)
    response = auth.post(
        prefix + "/approval-requests/from-drafts", json={"draft_ids": [str(draft.id)]}
    )
    assert response.status_code == 201, response.text
    item = response.json()[0]
    assert item["status"] == "PENDING"
    assert item["body"] == draft.body and item["sender"]["email"] == "sender@example.com"
    assert (
        auth.post(
            prefix + "/approval-requests/from-drafts", json={"draft_ids": [str(draft.id)]}
        ).status_code
        == 409
    )
    assert (
        auth.post(
            f"/api/approval-requests/{item['id']}/revoke",
            json={
                "expected_hash": item["payload_hash"],
                "expected_version": item["payload_version"],
                "reason": "Review again",
            },
        ).status_code
        == 200
    )
    assert (
        auth.post(
            prefix + "/approval-requests/from-drafts", json={"draft_ids": [str(draft.id)]}
        ).status_code
        == 201
    )
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0


@pytest.mark.parametrize("field", ["subject", "body"])
def test_blank_email_is_not_reserved(auth, db, configured, field):
    item = create(auth, configured, **{field: " "})
    token = proof(auth, configured[0], [item])
    assert (
        auth.post(
            f"/api/projects/{configured[0].id}/bulk-approval/approve",
            json={"challenge_token": token},
        ).status_code
        == 200
    )
    assert queue(auth, configured, item)[0].status_code == 409
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0


@pytest.mark.parametrize("failure", ["before", "during", "rejected", "quit"])
def test_smtp_outcome_classification(monkeypatch, failure):
    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            if failure == "before":
                raise OSError("before transmission")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            if failure == "quit":
                raise OSError("after acceptance")

        def send_message(self, message):
            if failure == "during":
                raise smtplib.SMTPServerDisconnected("uncertain")
            if failure == "rejected":
                raise smtplib.SMTPDataError(550, b"rejected")
            return {}

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    config = SmtpConfiguration("fake", 25, "", "", "sender@example.com", "Human", False, 1)
    if failure == "quit":
        send_with_configuration(config, "1", "recipient@example.com", "subject", "body")
    else:
        with pytest.raises(EmailDeliveryError) as exc:
            send_with_configuration(config, "1", "recipient@example.com", "subject", "body")
        assert exc.value.unknown == (failure == "during")
