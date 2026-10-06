"""Human queue/stop boundaries, append-only ledger; no acquisition or sending."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalRequest,
    EmailDelivery,
    FormDelivery,
    FormObservationJobEvent,
    OperationJob,
    ProjectMember,
)
from app.services import form_observation_jobs as service
from tests.conftest import PASSWORD
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_observation_runner import runner


@pytest.fixture
def managed(db, workspace, monkeypatch):
    for flag in service.FLAGS:
        monkeypatch.setenv(flag, "1")
    workspace[1].website_url = service.WEBSITE
    workspace[1].contact_url = service.CONTACT
    db.commit()
    return workspace


def base(managed):
    return f"/api/companies/{managed[1].id}/form-observation-jobs"


def start(auth, managed):
    response = auth.post(base(managed), json={})
    assert response.status_code == 202
    return response.json()["id"]


def test_start_queues_only_and_cancel_is_audited_idempotently(db, auth, managed):
    initial = auth.get(base(managed)).json()
    assert initial["can_start"] and initial["can_manage"]
    job_id = start(auth, managed)
    assert auth.post(base(managed), json={}).status_code == 409
    for _ in range(2):
        response = auth.post(f"/api/form-observation-jobs/{job_id}/cancel", json={})
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert not response.json()["execution_allowed"]
    events = db.scalars(select(FormObservationJobEvent)).all()
    assert {row.event_type for row in events} == {"QUEUED", "CANCELLED"}
    assert len(events) == 2 and all(row.principal_type == "HUMAN" for row in events)
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert auth.post(f"/api/operations/{job_id}/retry").status_code == 409


@pytest.mark.parametrize("flag", service.FLAGS)
def test_disabled_start_but_cancel_still_works(auth, managed, monkeypatch, flag):
    job_id = start(auth, managed)
    monkeypatch.delenv(flag)
    assert not auth.get(base(managed)).json()["can_start"]
    assert auth.post(base(managed), json={}).status_code == 409
    assert auth.post(f"/api/form-observation-jobs/{job_id}/cancel", json={}).status_code == 200


@pytest.mark.parametrize("body", [{"confirmed": True}, {"url": service.CONTACT}, {"run_id": "x"}])
def test_caller_cannot_supply_execution_or_binding(auth, managed, body):
    assert auth.post(base(managed), json=body).status_code == 422


def test_non_managed_url_rejected(db, auth, managed):
    managed[1].contact_url = "https://real.example/contact"
    db.commit()
    assert auth.post(base(managed), json={}).status_code == 409
    assert not auth.get(base(managed)).json()["can_start"]


def test_principals_and_project_permissions(db, auth, users, managed):
    job_id = start(auth, managed)
    routes = [
        base(managed),
        f"/api/form-observation-jobs/{job_id}/cancel",
        f"/api/form-observation-jobs/{job_id}/recover",
    ]
    for route in routes:
        assert (
            auth.post(route, json={}, headers={"Authorization": "Bearer fake-agent"}).status_code
            == 403
        )
    auth.cookies.clear()
    for route in routes:
        assert (
            auth.post(route, json={}, headers={"Authorization": "Bearer fake-agent"}).status_code
            == 403
        )
        assert auth.post(route, json={}).status_code == 401
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    for route in routes:
        assert auth.post(route, json={}).status_code == 404
    db.add(ProjectMember(project_id=managed[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(base(managed)).status_code == 200
    assert not auth.get(base(managed)).json()["can_manage"]
    for route in routes:
        assert auth.post(route, json={}).status_code == 404
    member = db.scalar(select(ProjectMember))
    member.role = "editor"
    db.commit()
    assert auth.post(routes[1], json={}).status_code == 200
    assert auth.post(routes[0], json={}).status_code == 202


def test_claim_stop_recover_ledger_and_legacy_cancel(db, auth, managed):
    from uuid import UUID, uuid4

    from sqlalchemy.orm import Session

    def sessions():
        return Session(bind=db.get_bind(), join_transaction_mode="create_savepoint")

    job_id = start(auth, managed)
    binding = runner.claim(sessions, UUID(job_id), uuid4())
    assert binding
    assert auth.post(f"/api/form-observation-jobs/{job_id}/recover", json={}).status_code == 409
    for _ in range(2):
        assert auth.post(f"/api/operations/{job_id}/cancel").status_code == 200
    job = db.get(OperationJob, UUID(job_id))
    job.lease_expires_at = db.scalar(text("SELECT clock_timestamp()")) - timedelta(seconds=1)
    db.commit()
    assert auth.get(base(managed)).json()["items"][0]["recoverable"]
    result = auth.post(f"/api/form-observation-jobs/{job_id}/recover", json={})
    assert result.status_code == 200 and result.json()["status"] == "cancelled"
    assert auth.post(f"/api/form-observation-jobs/{job_id}/recover", json={}).status_code == 409
    events = db.scalars(
        select(FormObservationJobEvent).order_by(FormObservationJobEvent.created_at)
    ).all()
    assert [row.event_type for row in events] == [
        "QUEUED",
        "CLAIMED",
        "CANCEL_REQUESTED",
        "RECOVERED",
    ]
    assert events[1].principal_type == "SYSTEM"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE form_observation_job_events SET reason_code='LAB_DISABLED'",
        "DELETE FROM form_observation_job_events",
        "TRUNCATE form_observation_job_events",
    ],
)
def test_ledger_cannot_be_changed(db, auth, managed, statement):
    start(auth, managed)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(statement))
    assert db.scalar(select(func.count()).select_from(FormObservationJobEvent)) == 1


def test_ledger_and_job_roll_back_together(db, managed, users):
    with db.begin_nested() as savepoint:
        service.enqueue(db, managed[1], users[0])
        assert db.scalar(select(func.count()).select_from(FormObservationJobEvent)) == 1
        savepoint.rollback()
    assert db.scalar(select(func.count()).select_from(OperationJob)) == 0
    assert db.scalar(select(func.count()).select_from(FormObservationJobEvent)) == 0


def test_old_schema_and_bounded_reads(db, auth, managed, monkeypatch):
    for query in ["limit=21", "offset=1001", "limit=0", "offset=-1"]:
        assert auth.get(base(managed) + "?" + query).status_code == 422
    monkeypatch.setattr(service, "available", lambda db: False)
    assert not auth.get(base(managed)).json()["available"]
    assert auth.post(base(managed), json={}).status_code == 409


def test_non_test_database_guard_and_error_redaction(db, auth, managed, monkeypatch):
    from uuid import UUID

    job_id = start(auth, managed)
    job = db.get(OperationJob, UUID(job_id))
    job.error_message = "raw-website-text-or-secret"
    db.commit()
    assert "raw-website-text-or-secret" not in auth.get(base(managed)).text
    original = db.scalar

    def scalar(statement, *args, **kwargs):
        if str(statement) == "SELECT current_database()":
            return "leadhive_location_preview"
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", scalar)
    assert not auth.get(base(managed)).json()["can_manage"]
    assert auth.post(f"/api/form-observation-jobs/{job_id}/cancel", json={}).status_code == 409


@pytest.mark.parametrize("field", ["run_id", "worker_id", "after_status", "reason_code"])
def test_ledger_rejects_forged_binding_and_raw_reason(db, auth, managed, field):
    from uuid import uuid4

    start(auth, managed)
    row = db.scalar(select(FormObservationJobEvent))
    values = {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in {"id", "created_at"}
    }
    values[field] = {"after_status": "completed", "reason_code": "raw-secret"}.get(field, uuid4())
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(FormObservationJobEvent(**values))
        db.flush()
    assert db.scalar(select(func.count()).select_from(FormObservationJobEvent)) == 1
