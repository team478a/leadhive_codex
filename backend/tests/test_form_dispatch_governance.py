"""Batch Human proof reuse and administrator limits; never real delivery."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import ApprovalRequest, ApprovedFormDispatch, FormDispatchLimits, OutreachAuditEvent
from app.services import approved_form as service
from app.services import approved_form_worker as worker
from app.services import human_approval as approval
from app.services.form_delivery_result import FormSubmissionResult
from tests.conftest import PASSWORD
from tests.test_approval_foundation import workspace as workspace
from tests.test_approved_email import proof, selection
from tests.test_approved_form import executor as executor
from tests.test_form_approval_preparation import form_source as form_source
from tests.test_form_approval_preparation import prepare


def bulk(auth, project, items, key=None):
    return auth.post(
        f"/api/projects/{project.id}/approved-form-dispatches",
        json={
            "items": [selection(i) for i in items],
            "idempotency_key": str(key or uuid4()),
        },
    )


def approve_bulk(auth, source, item):
    token = proof(auth, source[0], [item])
    response = auth.post(
        f"/api/projects/{source[0].id}/bulk-approval/approve", json={"challenge_token": token}
    )
    assert response.status_code == 200, response.text
    return token


def test_form_bulk_proof_reservation_idempotency_and_execution(
    auth, form_source, db, executor, monkeypatch
):
    item = prepare(auth, form_source)
    token = approve_bulk(auth, form_source, item)
    assert (
        auth.post(
            f"/api/projects/{form_source[0].id}/bulk-approval/approve",
            json={"challenge_token": token},
        ).status_code
        == 403
    )
    key = uuid4()
    response = bulk(auth, form_source[0], [item], key)
    assert response.status_code == 201, response.text
    row = response.json()["results"][0]
    assert row["error"] is None
    assert (
        bulk(auth, form_source[0], [item], key).json()["results"][0]["reservation"]["id"]
        == row["reservation"]["id"]
    )
    assert bulk(auth, form_source[0], [item]).json()["results"][0]["error"]
    monkeypatch.setattr(
        worker,
        "submit_form",
        lambda *a, **k: (
            None,
            FormSubmissionResult(200, "https://approval.example/thanks", False, "完了"),
        ),
    )
    claimed = service.claim(db)
    worker.run(db, claimed)
    assert db.get(ApprovedFormDispatch, claimed.id).status == "submitted"
    assert db.get(ApprovalRequest, UUID(item["id"])).status == "CONSUMED"


def test_partial_batch_reports_errors_without_sending(auth, form_source, db, monkeypatch):
    monkeypatch.setattr(settings, "outbound_enabled", False)
    item = prepare(auth, form_source)
    approve_bulk(auth, form_source, item)
    missing = item | {"id": str(uuid4())}
    response = bulk(auth, form_source[0], [item, missing])
    results = response.json()["results"]
    assert results[0]["reservation"] and not results[0]["error"]
    assert results[1]["error"] and not results[1]["reservation"]
    assert service.claim(db) is None
    assert len(db.scalars(select(ApprovedFormDispatch)).all()) == 1


def test_bulk_rejects_unapproved_version_conflicts_duplicates(auth, form_source):
    item = prepare(auth, form_source)
    assert bulk(auth, form_source[0], [item]).json()["results"][0]["error"]
    approve_bulk(auth, form_source, item)
    assert bulk(auth, form_source[0], [item | {"payload_version": 2}]).json()["results"][0]["error"]
    assert bulk(auth, form_source[0], [item, item]).status_code == 422


def update(auth, **values):
    return auth.put(
        "/api/form-dispatch-limits",
        json={
            "daily_limit": 500,
            "hourly_limit": 30,
            "minimum_interval_seconds": 60,
            "paused": False,
            "expected_version": 1,
            "password": PASSWORD,
            **values,
        },
    )


def test_admin_reauth_limits_version_and_audit(auth, users, db):
    assert not auth.get("/api/form-dispatch-limits").json()["can_manage"]
    assert update(auth).status_code == 404
    users[0].is_admin = True
    db.commit()
    assert update(auth, password="wrong").status_code == 403
    saved = update(auth, paused=True)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2 and saved.json()["daily_limit"] == 500
    assert update(auth).status_code == 409
    assert not service.capacity(db)
    event = db.scalar(
        select(OutreachAuditEvent).where(OutreachAuditEvent.event == "form limits changed")
    )
    assert "500" in event.reason and PASSWORD not in event.reason
    assert db.get(FormDispatchLimits, 1).updated_by_user_id == users[0].id
    assert len(auth.get("/api/form-dispatch-limits/audit").json()) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"daily_limit": 1001},
        {"hourly_limit": 101},
        {"minimum_interval_seconds": 59},
        {"daily_limit": 0},
        {"confirmed": True},
    ],
)
def test_limits_validate_range(auth, users, db, change):
    users[0].is_admin = True
    db.commit()
    assert update(auth, **change).status_code == 422


def test_limits_reauth_throttle(auth, users, db):
    users[0].is_admin = True
    db.commit()
    for _ in range(5):
        assert update(auth, password="wrong").status_code == 403
    assert update(auth).status_code == 429


def test_paused_queue_and_begin_cannot_start(auth, form_source, db, executor):
    item = prepare(auth, form_source)
    approve_bulk(auth, form_source, item)
    bulk(auth, form_source[0], [item])
    limits = db.get(FormDispatchLimits, 1)
    limits.paused = True
    db.commit()
    assert service.claim(db) is None
    limits.paused = False
    db.commit()
    claimed = service.claim(db)
    limits.paused = True
    db.commit()
    context = worker.inspect_delivery_profile()
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        worker.begin(db, claimed.id, claimed.worker_id, context)
    db.rollback()
    assert db.get(ApprovalRequest, UUID(item["id"])).status == "APPROVED"


@pytest.mark.parametrize("mixed", [False, True])
def test_agent_cannot_bulk_or_change_limits(auth, form_source, monkeypatch, mixed):
    from tests.test_approval_foundation import agent_token

    monkeypatch.setattr(settings, "agent_features_enabled", True)
    item = prepare(auth, form_source)
    token = agent_token(auth, form_source[:2])["token"]
    if not mixed:
        auth.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        auth.post(
            f"/api/projects/{form_source[0].id}/approved-form-dispatches",
            headers=headers,
            json={"items": [selection(item)], "idempotency_key": str(uuid4())},
        ).status_code
        == 403
    )
    assert auth.put("/api/form-dispatch-limits", headers=headers, json={}).status_code == 403


def test_configured_caps_count_unknown_and_fail_closed(
    auth, form_source, db, executor, monkeypatch
):
    item = prepare(auth, form_source)
    approve_bulk(auth, form_source, item)
    bulk(auth, form_source[0], [item])
    claimed = service.claim(db)
    worker.begin(db, claimed.id, claimed.worker_id, worker.inspect_delivery_profile())
    started = db.get(ApprovedFormDispatch, claimed.id).started_at
    monkeypatch.setattr(approval, "now", lambda: started + timedelta(seconds=60))
    limits = db.get(FormDispatchLimits, 1)
    limits.hourly_limit = 1
    db.commit()
    assert not service.capacity(db)
    limits.hourly_limit, limits.daily_limit = 2, 1
    db.commit()
    assert not service.capacity(db)
    limits.daily_limit = 500
    db.commit()
    assert service.capacity(db)
    db.delete(limits)
    db.commit()
    assert not service.capacity(db)


def test_bulk_other_project_and_viewer_denied(auth, form_source, users, db):
    from app.models import ProjectMember

    item = prepare(auth, form_source)
    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert bulk(auth, form_source[0], [item]).status_code == 404
    db.add(ProjectMember(project_id=form_source[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert bulk(auth, form_source[0], [item]).status_code == 404
    assert auth.get("/api/form-dispatch-limits/audit").status_code == 404
