"""Dedicated test database. Immutable metrics and authenticated explanatory ledger."""

import copy
import runpy
from pathlib import Path

import pytest
from alembic import op
from sqlalchemy import func, select

from app import feedback_evaluation_routes as routes
from app.config import settings
from app.models import FeedbackEvaluation, FeedbackEvaluationNote, ProjectMember
from offline_tests.test_improvement_workbench import dataset
from tests.test_ai import make_project

PERIOD = {"start": "2026-10-12T00:00:00Z", "end": "2026-10-13T00:00:00Z"}


def setup(auth, db, users, monkeypatch):
    users[0].is_admin = True
    db.commit()
    project = make_project(auth)
    monkeypatch.setattr(settings, "feedback_workbench_enabled", True)
    data = dataset()
    for record in data["records"]:
        record["project_id"] = project["id"]
    monkeypatch.setattr(routes, "export_feedback", lambda *_: copy.deepcopy(data))
    return project, f"/api/projects/{project['id']}/feedback-evaluations", data


def test_save_compare_idempotent_and_append_notes(auth, db, users, monkeypatch):
    _, base, data = setup(auth, db, users, monkeypatch)
    first = auth.post(base, json=PERIOD)
    assert first.status_code == 200
    item = first.json()
    original = copy.deepcopy(item["report"])
    assert item["report"]["evaluation_samples"] == 1
    assert item["runtime_applied"] is False and item["comparison"] is None
    assert first.headers["cache-control"] == "no-store"
    assert auth.post(base, json=PERIOD).json()["id"] == item["id"]
    compared = auth.post(base, json={**PERIOD, "previous_id": item["id"]}).json()
    assert compared["comparison"]["improvement_demonstrated"] is False
    path = base + f"/{item['id']}/notes"
    for version in range(2):
        response = auth.post(
            path,
            json={
                "expected_version": version,
                "reason": "NOT_APPLIED",
                "note": f"Not deployed {version}",
            },
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["version"] == version + 1
        assert updated["notes"][-1]["actor_id"] == str(users[0].id)
        assert updated["notes"][-1]["principal_verified"] is True
        assert updated["report"] == original
    assert (
        auth.post(
            path, json={"expected_version": 0, "reason": "OTHER", "note": "stale"}
        ).status_code
        == 409
    )
    listed = auth.get(base).json()["items"]
    assert len(listed) == 2
    assert next(r for r in listed if r["id"] == item["id"])["version"] == 2
    # Changed source creates a new measurement, preserving previous metrics.
    data["records"] = []
    changed = auth.post(base, json={**PERIOD, "previous_id": item["id"]}).json()
    assert "COHORT_CHANGED" in changed["comparison"]["limitations"]
    assert changed["report"]["metrics"]["collection_precision"] is None
    assert db.scalar(select(func.count()).select_from(FeedbackEvaluationNote)) == 2


def test_scope_roles_agent_flag_and_no_forged_actor(auth, client, db, users, monkeypatch):
    project, base, _ = setup(auth, db, users, monkeypatch)
    item = auth.post(base, json=PERIOD).json()
    assert auth.get(base, headers={"Authorization": "Bearer agent-only-test"}).status_code in {
        401,
        403,
    }
    note_path = base + f"/{item['id']}/notes"
    body = {"expected_version": 0, "reason": "OTHER", "note": "reason"}
    assert auth.post(note_path, json={**body, "actor_id": str(users[1].id)}).status_code == 422
    other = make_project(auth)
    other_base = f"/api/projects/{other['id']}/feedback-evaluations"
    assert auth.post(other_base, json={**PERIOD, "previous_id": item["id"]}).status_code == 404
    assert auth.post(other_base + f"/{item['id']}/notes", json=body).status_code == 404
    users[0].is_admin = False
    db.commit()
    assert auth.get(base).status_code == 404
    assert auth.post(base, json=PERIOD).status_code == 404
    users[0].is_admin = True
    users[1].is_admin = True
    db.add(ProjectMember(project_id=project["id"], user_id=users[1].id, role="editor"))
    db.commit()
    from tests.conftest import PASSWORD

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert client.get(base).status_code == 404
    assert client.post(base, json=PERIOD).status_code == 404
    assert client.post(note_path, json=body).status_code == 404
    monkeypatch.setattr(settings, "feedback_workbench_enabled", False)
    assert client.get(base).status_code == 404


def test_invalid_dates_notes_and_export_fail_without_writes(auth, db, users, monkeypatch):
    _, base, data = setup(auth, db, users, monkeypatch)
    assert auth.post(base, json={**PERIOD, "end": PERIOD["start"]}).status_code == 422
    assert auth.post(base, json={**PERIOD, "start": "2026-10-12T00:00:00"}).status_code == 422
    data["records"][0]["project_id"] = "other"
    assert auth.post(base, json=PERIOD).status_code == 409
    assert db.scalar(select(func.count()).select_from(FeedbackEvaluation)) == 0
    data["records"] = []
    item = auth.post(base, json=PERIOD).json()
    path = base + f"/{item['id']}/notes"
    for reason, note in [("INVALID", "x"), ("OTHER", " "), ("OTHER", "x" * 2001)]:
        assert (
            auth.post(
                path, json={"expected_version": 0, "reason": reason, "note": note}
            ).status_code
            == 422
        )
    assert db.scalar(select(func.count()).select_from(FeedbackEvaluationNote)) == 0


def test_empty_real_export_and_downgrade_guard(auth, db, users, monkeypatch):
    users[0].is_admin = True
    db.commit()
    project = make_project(auth)
    monkeypatch.setattr(settings, "feedback_workbench_enabled", True)
    base = f"/api/projects/{project['id']}/feedback-evaluations"
    result = auth.post(base, json=PERIOD)
    assert result.status_code == 200
    report = result.json()["report"]
    assert report["dataset_kind"] == "AUTHORIZED_EXPORT"
    assert report["evaluation_samples"] == 0 and report["metrics"]["api_cost"] is None
    assert "tanaka" not in str(report)
    migration = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "migrations/versions/1bf54b61cc07_add_evaluation_checkpoints_and_operator_.py"
        )
    )
    monkeypatch.setattr(op, "get_bind", lambda: db.connection())
    with pytest.raises(RuntimeError, match="Export and remove"):
        migration["downgrade"]()
