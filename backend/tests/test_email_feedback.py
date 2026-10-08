import hashlib
import hmac
import json
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.config import settings
from app.model_approved_email import ApprovedEmailBatch
from app.model_email_feedback import EmailFeedbackEvent, EmailHealthState
from app.models import EmailDelivery, OutreachAuditEvent, ProjectMember, SuppressionEntry
from app.schema_email_feedback import FeedbackInput
from app.services import approved_email_worker, email_feedback, human_approval
from tests.conftest import PASSWORD
from tests.test_approved_email import approved, queue


@pytest.fixture
def approval_workspace(db, users):
    from tests.test_approval_foundation import workspace

    return workspace.__wrapped__(db, users)


@pytest.fixture
def configured(monkeypatch, approval_workspace):
    from tests.test_approved_email import configured

    return configured.__wrapped__(monkeypatch, approval_workspace)


def sent(auth, db, configured, monkeypatch):
    proposal = approved(auth, configured)
    batch, _ = queue(auth, configured, proposal)
    assert batch.status_code == 201
    job = approved_email_worker.claim(db)
    monkeypatch.setattr(approved_email_worker, "send_with_configuration", lambda *a, **kw: None)
    approved_email_worker.run(db, job)
    assert job.status == "sent"
    return job


def body(job, kind="complaint"):
    return {
        "event_key": str(uuid4()),
        "delivery_id": str(job.id),
        "recipient": job.recipient_email,
        "kind": kind,
        "occurred_at": human_approval.now().isoformat(),
    }


def test_feedback_idempotent_suppression_and_manual_review(auth, db, configured, monkeypatch):
    job = sent(auth, db, configured, monkeypatch)
    url = f"/api/projects/{configured[0].id}"
    event = body(job)
    assert auth.post(url + "/email-feedback", json=event).status_code == 201
    assert auth.post(url + "/email-feedback", json=event).status_code == 201
    assert db.scalar(select(func.count()).select_from(EmailFeedbackEvent)) == 1
    suppress = db.scalar(select(SuppressionEntry))
    assert suppress.email == job.recipient_email and suppress.domain == ""
    health = auth.get(url + "/email-health").json()
    assert health["paused"] and health["counts"]["complaint"] == 1
    reset = {"expected_stopped_at": health["stopped_at"], "password": "wrong"}
    assert auth.post(url + "/email-health/review", json=reset).status_code == 403
    reset["password"] = PASSWORD
    assert auth.post(url + "/email-health/review", json=reset).status_code == 200
    assert auth.post(url + "/email-health/review", json=reset).status_code == 409
    assert db.scalar(select(SuppressionEntry))
    assert job.status == "sent"  # Evidence never overwrites SMTP or retries.
    changed = {**event, "kind": "delivered"}
    assert auth.post(url + "/email-feedback", json=changed).status_code == 409
    assert db.scalar(
        select(OutreachAuditEvent.id).where(OutreachAuditEvent.event == "email health reviewed")
    )


def test_feedback_boundaries_and_ledger(auth, db, configured, users, monkeypatch):
    job = sent(auth, db, configured, monkeypatch)
    url = f"/api/projects/{configured[0].id}/email-feedback"
    event = body(job, "soft_bounce")
    assert auth.post(url, json={**event, "recipient": "other@example.com"}).status_code == 409
    assert (
        auth.post(
            url, json={**event, "occurred_at": (job.started_at - timedelta(days=1)).isoformat()}
        ).status_code
        == 422
    )
    assert auth.post(url, json={**event, "confirmed": True}).status_code == 422
    assert (
        auth.post(url, json=event, headers={"Authorization": "Bearer lh_agent_fake"}).status_code
        == 403
    )
    assert auth.post(url, json=event).status_code == 201
    assert not db.scalar(select(SuppressionEntry.id))
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(text("DELETE FROM email_feedback_events"))
    configured[0].user_id = users[1].id
    db.add(ProjectMember(project_id=configured[0].id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(url).status_code == 200
    assert auth.post(url, json=body(job)).status_code == 404


def test_circuit_breaker_pause_and_pre_send_guard(auth, db, configured, monkeypatch):
    proposal = approved(auth, configured)
    response, _ = queue(auth, configured, proposal)
    job = approved_email_worker.claim(db)
    row = email_feedback.state(db, configured[0].id)
    row.paused, row.reason, row.stopped_at = True, "test stop", human_approval.now()
    db.commit()
    monkeypatch.setattr(
        approved_email_worker,
        "send_with_configuration",
        lambda *a, **kw: pytest.fail("must not send"),
    )
    approved_email_worker.run(db, job)
    assert job.status == "blocked"
    assert (
        auth.post(f"/api/approved-email-batches/{response.json()['id']}/resume").status_code == 409
    )


@pytest.mark.parametrize("kind", ["hard_bounce", "unknown"])
def test_health_threshold(auth, db, configured, monkeypatch, kind):
    job = sent(auth, db, configured, monkeypatch)
    for _ in range(9):
        from app.models import OutreachDraft

        draft = OutreachDraft(
            company_id=job.company_id, channel="email", subject="test", body="test"
        )
        db.add(draft)
        db.flush()
        clone = EmailDelivery(
            company_id=job.company_id,
            draft_id=draft.id,
            recipient_email=job.recipient_email,
            subject="test",
            body="test",
            status="unknown" if kind == "unknown" else "sent",
            scheduled_for=human_approval.now(),
            started_at=human_approval.now(),
            confirmed_at=human_approval.now(),
        )
        db.add(clone)
        db.flush()
        if kind == "hard_bounce":
            email_feedback.record(
                db, FeedbackInput(**body(clone, "hard_bounce")), "HUMAN", auth_user(db)
            )
    row, counts = email_feedback.evaluate(db, configured[0].id)
    assert row.paused and counts["attempted"] == 10
    batch = db.scalar(select(ApprovedEmailBatch))
    assert batch.status == "paused"


def auth_user(db):
    from app.models import User

    return db.scalar(select(User).where(User.email == "user0@example.com"))


def test_signed_webhook(auth, client, db, configured, monkeypatch):
    from app.model_approved_email import EmailSendAttempt

    job = sent(auth, db, configured, monkeypatch)
    event = body(job, "delivered")
    event["message_id"] = db.scalar(select(EmailSendAttempt.message_id))
    raw = json.dumps(event).encode()
    secret = "test-only-webhook-secret-32-characters"
    monkeypatch.setattr(settings, "email_feedback_webhook_enabled", True)
    monkeypatch.setattr(settings, "email_feedback_webhook_secret", secret)
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    headers = {
        "x-leadhive-timestamp": timestamp,
        "x-leadhive-signature": signature,
        "content-type": "application/json",
    }
    assert (
        client.post("/api/webhooks/email-feedback", content=raw, headers=headers).status_code == 403
    )  # Human cookie rejected
    client.cookies.clear()
    assert (
        client.post(
            "/api/webhooks/email-feedback",
            content=raw,
            headers={**headers, "x-leadhive-signature": "0" * 64},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/webhooks/email-feedback", content=raw, headers=headers).status_code == 200
    )
    assert (
        client.post("/api/webhooks/email-feedback", content=raw, headers=headers).status_code == 200
    )
    assert db.scalar(select(func.count()).select_from(EmailFeedbackEvent)) == 1
    assert not db.get(EmailHealthState, configured[0].id).paused
    assert job.status == "sent"


def test_review_owner_throttle_and_unknown_preserved(auth, db, configured, users, monkeypatch):
    job = sent(auth, db, configured, monkeypatch)
    job.status = "unknown"
    db.commit()
    url = f"/api/projects/{configured[0].id}"
    assert auth.post(url + "/email-feedback", json=body(job)).status_code == 201
    stopped = auth.get(url + "/email-health").json()["stopped_at"]
    payload = {"expected_stopped_at": stopped, "password": "wrong"}
    for _ in range(5):
        assert auth.post(url + "/email-health/review", json=payload).status_code == 403
    payload["password"] = PASSWORD
    assert auth.post(url + "/email-health/review", json=payload).status_code == 429
    assert job.status == "unknown"
    configured[0].user_id = users[1].id
    db.add(ProjectMember(project_id=configured[0].id, user_id=users[0].id, role="editor"))
    db.commit()
    assert auth.post(url + "/email-health/review", json=payload).status_code == 404


@pytest.mark.parametrize("invalid", ["expired", "message", "json", "oversize", "unknown_field"])
def test_provider_validation(auth, client, db, configured, monkeypatch, invalid):
    from app.model_approved_email import EmailSendAttempt

    job = sent(auth, db, configured, monkeypatch)
    event = body(job, "hard_bounce")
    event["message_id"] = db.scalar(select(EmailSendAttempt.message_id))
    secret = "test-only-webhook-secret-32-characters"
    monkeypatch.setattr(settings, "email_feedback_webhook_enabled", True)
    monkeypatch.setattr(settings, "email_feedback_webhook_secret", secret)
    timestamp = str(int(time.time()) - (600 if invalid == "expired" else 0))
    if invalid == "message":
        event["message_id"] = "other-message"
    if invalid == "unknown_field":
        event["confirmed"] = True
    raw = b"{" if invalid == "json" else json.dumps(event).encode()
    if invalid == "oversize":
        raw = b"x" * 16385
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    client.cookies.clear()
    response = client.post(
        "/api/webhooks/email-feedback",
        content=raw,
        headers={"x-leadhive-timestamp": timestamp, "x-leadhive-signature": signature},
    )
    assert (
        response.status_code
        == {"expired": 403, "message": 409, "json": 422, "oversize": 413, "unknown_field": 422}[
            invalid
        ]
    )
    assert db.scalar(select(func.count()).select_from(EmailFeedbackEvent)) == 0
