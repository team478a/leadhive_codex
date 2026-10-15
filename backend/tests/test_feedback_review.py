"""Dedicated test DB only. Proposal decisions never modify runtime or send authority."""

import copy
import runpy
from pathlib import Path

import pytest
from alembic import op
from fastapi import Response
from sqlalchemy import func, select

from app import feedback_review_routes as routes
from app.config import settings
from app.models import FeedbackProposal, FeedbackProposalDecision, ProjectMember
from offline_tests.test_improvement_workbench import dataset
from tests.test_ai import make_project


def setup(auth, db, users, monkeypatch):
    users[0].is_admin = True
    db.commit()
    project = make_project(auth)
    monkeypatch.setattr(settings, "feedback_workbench_enabled", True)
    data = dataset()
    for row in data["records"]:
        row["project_id"] = project["id"]
    monkeypatch.setattr(routes, "export_feedback", lambda *_: copy.deepcopy(data))
    base = f"/api/projects/{project['id']}/feedback-proposals"
    assert auth.post(base + "/analyze").status_code == 200
    proposal = auth.get(base).json()["items"][0]
    return project, base, proposal


def test_decisions_restore_append_and_reanalysis_is_idempotent(auth, db, users, monkeypatch):
    _, base, original = setup(auth, db, users, monkeypatch)
    path = base + f"/{original['id']}"
    saved_report = copy.deepcopy(original["report"])
    for version, state in enumerate(["ACCEPTED", "REJECTED", "DEFERRED"]):
        result = auth.post(
            path + "/decisions",
            json={"expected_version": version, "state": state, "reason": "Human research decision"},
        )
        assert result.status_code == 200
        assert result.json()["runtime_applied"] is False
    stale = auth.post(
        path + "/decisions", json={"expected_version": 1, "state": "ACCEPTED", "reason": "stale"}
    )
    assert stale.status_code == 409
    restored = auth.post(
        path + "/restore",
        json={
            "expected_version": 3,
            "restore_version": 1,
            "reason": "restore previous research choice",
        },
    ).json()
    assert restored["version"] == 4 and restored["state"] == "ACCEPTED"
    assert restored["history"][-1]["restored_from"] == 1
    assert len(restored["history"]) == 4 and restored["report"] == saved_report
    assert auth.post(base + "/analyze").status_code == 200
    assert len(auth.get(base).json()["items"]) == 1
    assert db.scalar(select(func.count()).select_from(FeedbackProposalDecision)) == 4


def test_owner_admin_boundary_flag_agent_and_other_project(auth, client, db, users, monkeypatch):
    project, base, proposal = setup(auth, db, users, monkeypatch)
    users[0].is_admin = False
    db.commit()
    assert auth.get(base).status_code == 404
    assert auth.post(base + "/analyze").status_code == 404
    users[0].is_admin = True
    db.commit()
    assert auth.get(base, headers={"Authorization": "Bearer agent-only-test"}).status_code in {
        401,
        403,
    }
    from tests.conftest import PASSWORD

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    users[1].is_admin = True
    db.add(ProjectMember(project_id=project["id"], user_id=users[1].id, role="editor"))
    db.commit()
    assert client.get(base).status_code == 404
    assert client.get(base + "/status").status_code == 404
    assert (
        client.post(
            base + f"/{proposal['id']}/decisions",
            json={"expected_version": 0, "state": "ACCEPTED", "reason": "outside owner boundary"},
        ).status_code
        == 404
    )
    monkeypatch.setattr(settings, "feedback_workbench_enabled", False)
    assert client.get(base).status_code == 404


def test_status_is_read_only_and_owner_admin_only(auth, db, users, monkeypatch):
    _, base, _ = setup(auth, db, users, monkeypatch)
    count = db.scalar(select(func.count()).select_from(FeedbackProposal))
    for enabled in (True, False):
        monkeypatch.setattr(settings, "feedback_workbench_enabled", enabled)
        response = auth.get(base + "/status")
        assert response.status_code == 200
        assert response.json() == {
            "enabled": enabled,
            "provenance_enabled": settings.feedback_provenance_enabled,
            "runtime_applied": False,
        }
        assert response.headers["cache-control"] == "no-store"
    assert db.scalar(select(func.count()).select_from(FeedbackProposal)) == count
    assert auth.post(base + "/analyze").status_code == 404
    assert auth.get(
        base + "/status", headers={"Authorization": "Bearer agent-only-test"}
    ).status_code in {401, 403}
    users[0].is_admin = False
    db.commit()
    assert auth.get(base + "/status").status_code == 404


def test_period_is_captured_in_proposal_and_idempotency(auth, db, users, monkeypatch):
    project, base, _ = setup(auth, db, users, monkeypatch)
    data = dataset()
    for row in data["records"]:
        row["project_id"] = project["id"]

    def period_export(*_, start, end):
        value = copy.deepcopy(data)
        value["period"] = {
            "start_inclusive": start.isoformat(),
            "end_exclusive": end.isoformat(),
        }
        return value

    monkeypatch.setattr(routes, "export_feedback", period_export)
    params = {"start": "2026-10-12T00:00:00Z", "end": "2026-10-13T00:00:00Z"}
    first = auth.post(base + "/analyze", json=params)
    assert first.status_code == 200
    assert first.json()["proposal_ids"]
    repeat = auth.post(base + "/analyze", json=params)
    assert repeat.json()["proposal_ids"] == first.json()["proposal_ids"]
    items = auth.get(base).json()["items"]
    saved = next(r for r in items if r["id"] == first.json()["proposal_ids"][0])
    assert saved["report"]["period"] == first.json()["period"]
    different = auth.post(base + "/analyze", json={**params, "end": "2026-10-14T00:00:00Z"})
    assert different.status_code == 200
    assert set(different.json()["proposal_ids"]).isdisjoint(first.json()["proposal_ids"])


def test_regression_cannot_be_accepted_and_reason_is_required(auth, db, users, monkeypatch):
    _, base, proposal = setup(auth, db, users, monkeypatch)
    item = db.get(FeedbackProposal, proposal["id"])
    altered = copy.deepcopy(item.report)
    altered["comparison"]["regressions"] = 1
    item.report = altered
    db.commit()
    path = base + f"/{proposal['id']}"
    assert (
        auth.post(
            path + "/decisions",
            json={"expected_version": 0, "state": "ACCEPTED", "reason": "accept regression"},
        ).status_code
        == 409
    )
    assert (
        auth.post(
            path + "/decisions", json={"expected_version": 0, "state": "REJECTED", "reason": " "}
        ).status_code
        == 422
    )
    assert (
        auth.post(
            path + "/restore",
            json={"expected_version": 1, "restore_version": 9, "reason": "missing"},
        ).status_code
        == 409
    )
    assert db.scalar(select(func.count()).select_from(FeedbackProposalDecision)) == 0


def test_empty_real_export_does_not_infer_success(auth, db, users, monkeypatch):
    users[0].is_admin = True
    db.commit()
    project = make_project(auth)
    monkeypatch.setattr(settings, "feedback_workbench_enabled", True)
    result = routes.analyze_saved(project["id"], Response(), db, users[0])
    assert result["proposal_ids"] == [] and result["api_calls"] == 0
    assert result["runtime_applied"] is False


def test_downgrade_refuses_nonempty_ledger(auth, db, users, monkeypatch):
    setup(auth, db, users, monkeypatch)
    migration = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "migrations/versions/7ce07249774c_add_feedback_proposal_decision_ledger.py"
        )
    )
    monkeypatch.setattr(op, "get_bind", lambda: db.connection())
    with pytest.raises(RuntimeError, match="Export and remove"):
        migration["downgrade"]()
    assert db.scalar(select(func.count()).select_from(FeedbackProposal)) == 1
