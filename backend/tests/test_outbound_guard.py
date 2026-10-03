from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import worker
from app.config import Settings, settings
from app.models import OperationJob
from app.services import email_delivery, form_codex, form_delivery, form_delivery_result
from tests.test_approval_foundation import workspace as workspace


@pytest.fixture(autouse=True)
def sending_stopped(legacy_delivery_test_mode, monkeypatch):
    monkeypatch.setattr(settings, "outbound_enabled", False)


@pytest.mark.parametrize(
    "method,path,payload",
    [
        (
            "POST",
            "/outreach-drafts/{id}/email-delivery",
            {"recipient_email": "target@example.com", "confirmed": True},
        ),
        ("POST", "/email-deliveries/{id}/retry", {"confirmed": True}),
        ("POST", "/outreach-drafts/{id}/form-delivery", {"confirmed": True}),
        ("GET", "/outreach-drafts/{id}/form-assist", None),
        (
            "POST",
            "/outreach-drafts/{id}/form-assist-delivery",
            {"status": "submitted", "confirmed": True},
        ),
        ("POST", "/form-delivery-batches/{id}/execute", {"confirmed": True}),
        ("POST", "/form-delivery-batch-items/{id}/retry", {"confirmed": True}),
        ("POST", "/form-codex-queue/{id}", {"status": "running", "confirmed": True}),
        ("POST", "/email-campaigns/{id}/resume", {}),
        (
            "POST",
            "/projects/{id}/email-campaigns",
            {
                "name": "Blocked",
                "template_id": str(uuid4()),
                "company_ids": [str(uuid4())],
                "confirmed": True,
            },
        ),
    ],
)
def test_legacy_confirmed_cannot_bypass_stop(auth, method, path, payload):
    response = auth.request(method, "/api" + path.format(id=uuid4()), json=payload)
    assert response.status_code == 503, response.text
    assert "外部送信を停止" in response.json()["detail"]


def test_smtp_test_and_status_endpoint(auth, db, users):
    users[0].is_admin = True
    db.commit()
    response = auth.post(
        "/api/admin/smtp-settings/test", json={"recipient_email": "blocked@example.com"}
    )
    assert response.status_code == 503
    assert auth.get("/api/outreach-execution-status").json() == {"outbound_enabled": False}


@pytest.mark.parametrize(
    "action",
    [
        lambda: email_delivery.send_email(None, "test", "a@example.com", "Subject", "Body"),
        lambda: email_delivery.send_test_email(None, "a@example.com"),
        lambda: email_delivery.send_with_configuration(
            None, "test", "a@example.com", "Subject", "Body"
        ),
        lambda: form_delivery.submit_form("https://example.com", {}),
        lambda: form_delivery_result.submit_and_verify(
            None,
            "https://example.com",
            {},
            original_form_url="https://example.com",
            confirmation_expected=True,
        ),
        lambda: form_delivery_result._request_result(None, "POST", "https://example.com", {}),
        lambda: form_codex.build_codex_form_payload(None, None, None),
        lambda: worker.run_email_delivery(None, None),
        lambda: worker.run_form_delivery(None, None, uuid4()),
    ],
)
def test_executor_denies_before_db_or_network(action):
    with pytest.raises(HTTPException) as error:
        action()
    assert error.value.status_code == 503


def test_default_without_configuration_is_off(monkeypatch):
    monkeypatch.delenv("OUTBOUND_ENABLED", raising=False)
    assert Settings(_env_file=None).outbound_enabled is False


def test_collection_runs_with_queued_form_untouched(db, workspace, monkeypatch):
    project, company = workspace
    queued = OperationJob(
        project_id=project.id, operation_type="form_delivery", payload={"batch_id": str(uuid4())}
    )
    collection = OperationJob(project_id=project.id, operation_type="collect_search", payload={})
    db.add_all([queued, collection])
    db.flush()
    queued_id, collection_id = queued.id, collection.id

    @contextmanager
    def session():
        yield db

    calls = []
    monkeypatch.setattr(worker, "SessionLocal", session)
    monkeypatch.setattr(worker, "sync_inbound_mail", lambda db: False)
    monkeypatch.setattr(worker, "run_collection", lambda db, job, worker_id: calls.append(job.id))
    assert worker.run_once()
    assert calls == [collection_id]
    db.expire_all()
    assert db.get(OperationJob, queued_id).status == "queued"
    assert db.get(OperationJob, queued_id).attempt_count == 0
    assert db.get(OperationJob, collection_id).status == "completed"
    assert worker.claim_email_delivery(None) is None
    assert worker.claim_job(db) is None


def test_stale_form_not_recovered_for_automatic_retry(db, workspace):
    project, company = workspace
    stale = OperationJob(
        project_id=project.id,
        operation_type="form_delivery",
        status="running",
        worker_id=uuid4(),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db.add(stale)
    db.flush()
    assert worker.recover_stale_jobs(db) == (0, 0)
    assert db.scalar(select(OperationJob.status).where(OperationJob.id == stale.id)) == "running"


def test_stopped_codex_queue_is_empty_without_breaking_company_reads(auth, workspace):
    project, company = workspace
    response = auth.get(f"/api/projects/{project.id}/form-codex-queue")
    assert response.status_code == 200
    assert response.json() == []


def test_smtp_rechecks_stop_before_send(monkeypatch):
    monkeypatch.setattr(settings, "outbound_enabled", True)

    class FakeSmtp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            monkeypatch.setattr(settings, "outbound_enabled", False)
            return self

        def __exit__(self, *args):
            pass

        def send_message(self, message):
            raise AssertionError("Network send must not be invoked")

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSmtp)
    config = email_delivery.SmtpConfiguration(
        "smtp.example.com", 587, "", "", "sender@example.com", "Sender", False, 20
    )
    with pytest.raises(HTTPException) as error:
        email_delivery.send_with_configuration(config, "test", "a@example.com", "Subject", "Body")
    assert error.value.status_code == 503
