"""Read-only observation diagnostics: synthetic evidence in a dedicated test DB."""

import copy
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from app import form_observation_routes as routes
from app.config import settings
from app.models import ApprovalRequest, EmailDelivery, FormDelivery, ProjectMember
from tests.conftest import PASSWORD
from tests.test_approval_foundation import agent_token
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_observation_storage import receipt as receipt
from tests.test_form_observation_storage import store


def url(receipt):
    return f"/api/companies/{receipt[1].id}/form-observations"


def test_read_is_bounded_non_authoritative_and_read_only(db, receipt, auth, users):
    store.save(db, receipt[3], users[0])
    db.commit()
    for _ in range(2):
        response = auth.get(url(receipt))
        assert response.status_code == 200
        data = response.json()
        assert data["available"] and not data["has_more"]
        assert data["latest_job"]["status"] == "completed"
        item = data["items"][0]
        assert item["freshness"] == "CURRENT"
        assert not item["execution_allowed"] and not item["eligible_for_approval"]
        assert item["diagnostic"]["captcha_state"] == "UNVERIFIED"
        assert "binding" not in item and "structure_summary" not in item
        assert "canonical_snapshot" not in item
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert auth.post(url(receipt), json={"confirmed": True}).status_code == 405
    assert auth.get(url(receipt) + "?offset=1").json()["items"] == []


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "offset=-1", "offset=10001"])
def test_pagination_limits(auth, receipt, query):
    assert auth.get(url(receipt) + "?" + query).status_code == 422


def test_viewer_can_read_but_outside_project_cannot(db, receipt, auth, users):
    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert auth.get(url(receipt)).status_code == 404
    db.add(ProjectMember(project_id=receipt[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(url(receipt)).status_code == 200


def test_agent_and_mixed_principals_rejected(auth, receipt, workspace, monkeypatch):
    monkeypatch.setattr(settings, "agent_features_enabled", True)
    issued = agent_token(auth, workspace)
    headers = {"Authorization": f"Bearer {issued['token']}"}
    assert auth.get(url(receipt), headers=headers).status_code == 403
    auth.cookies.clear()
    assert auth.get(url(receipt), headers=headers).status_code == 403
    assert auth.get(url(receipt)).status_code == 401


def test_old_schema_is_reported_without_querying_missing_tables(auth, receipt, monkeypatch):
    monkeypatch.setattr(routes, "storage_available", lambda db: False)
    assert auth.get(url(receipt)).json() == {
        "available": False,
        "items": [],
        "has_more": False,
        "latest_job": None,
    }


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE form_observation_evidence RENAME TO hidden_observation_evidence_test",
        "ALTER TABLE form_observation_events RENAME TO hidden_observation_events_test",
        "ALTER FUNCTION form_observation_source(uuid) RENAME TO hidden_observation_source_test",
    ],
)
def test_missing_storage_components_are_detected_in_postgresql(db, auth, receipt, statement):
    # DDL is confined to a rollback savepoint in this dedicated test DB.
    savepoint = db.begin_nested()
    try:
        db.execute(text(statement))
        result = auth.get(url(receipt))
        assert result.status_code == 200
        assert result.json()["available"] is False
    finally:
        savepoint.rollback()


def test_changed_source_and_retirement(db, receipt, users, auth):
    row = store.save(db, receipt[3], users[0])
    db.commit()
    receipt[1].website_url = "https://managed.example/changed/"
    db.commit()
    assert auth.get(url(receipt)).json()["items"][0]["freshness"] == "SOURCE_CHANGED"
    store.retire(db, row.id, users[0], expected_hash=row.snapshot_hash)
    db.commit()
    assert auth.get(url(receipt)).json()["items"][0]["freshness"] == "RETIRED"


def test_expired_history_and_corrupt_projection_are_never_permission(db, receipt, users):
    row = store.save(db, receipt[3], users[0])
    db.commit()
    source = store.source_hash(db, receipt[1].id)
    result = routes.project_record(
        row, retired=False, source_hash=source, now=row.expires_at + timedelta(seconds=1)
    )
    assert result.freshness == "EXPIRED" and not result.execution_allowed
    corrupted = SimpleNamespace(
        **{
            key: getattr(row, key)
            for key in (
                "id",
                "project_id",
                "company_id",
                "operation_job_id",
                "run_id",
                "observed_at",
                "expires_at",
                "snapshot_hash",
                "snapshot",
                "canonical_snapshot",
            )
        }
    )
    corrupted.snapshot = copy.deepcopy(corrupted.snapshot)
    corrupted.snapshot["body"] = "<script>alert('secret')</script>"
    result = routes.project_record(
        corrupted,
        retired=False,
        source_hash=source,
        now=db.scalar(text("SELECT clock_timestamp()")),
    )
    assert result.freshness == "INVALID" and result.diagnostic is None
    assert "secret" not in result.model_dump_json()
    # A malformed reason must reset the whole projection even if its bytes hash matches.
    corrupted.snapshot = copy.deepcopy(row.snapshot)
    corrupted.snapshot["reason_code"] = {"unexpected": "secret"}
    corrupted.canonical_snapshot = json.dumps(corrupted.snapshot)
    corrupted.snapshot_hash = hashlib.sha256(corrupted.canonical_snapshot.encode()).hexdigest()
    result = routes.project_record(
        corrupted,
        retired=False,
        source_hash=source,
        now=db.scalar(text("SELECT clock_timestamp()")),
    )
    assert result.freshness == "INVALID" and result.reason == "INTEGRITY_INVALID"
    assert result.diagnostic is None and "secret" not in result.model_dump_json()
