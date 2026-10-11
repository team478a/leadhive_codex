import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.live_input_routes import PREFIX, stored
from app.main import app
from app.models import Activity, Company, Project, ProjectMember, SuppressionEntry, TargetProfile


@pytest.fixture
def trial(auth, db, users, monkeypatch):
    monkeypatch.setattr(settings, "live_form_input_enabled", True)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(
        settings, "settings_encryption_key", "TXo8wyai6a-uQTN15jhU7_la86LCSPzFR6pMXGkYslM="
    )
    profile = TargetProfile(user_id=users[0].id, profile_name="Input only")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=users[0].id,
        target_profile_id=profile.id,
        project_name="Input only",
        sales_objective="No send",
        region="test",
    )
    db.add(project)
    db.flush()
    company = Company(
        project_id=project.id,
        company_name="Synthetic",
        source="url",
        domain="synthetic.example",
        contact_url="https://synthetic.example/contact",
    )
    db.add(company)
    db.commit()
    plan = {
        "formUrl": company.contact_url,
        "termsConfirmed": True,
        "values": {"email": "fixture@example.com"},
        "choices": {},
        "consents": {},
    }
    return auth, company, plan, f"/api/companies/{company.id}/live-input-trials"


def issue(trial):
    client, _, plan, path = trial
    response = client.post(path, json=plan)
    assert response.status_code == 201, response.text
    return response.json()


def check(task, phase="LOAD", **body):
    with TestClient(app) as pc:
        return pc.post(
            f"/api/live-input-trials/{task['trialId']}/check",
            headers={"Authorization": f"Bearer {task['token']}"},
            json={"requestHash": task["requestHash"], "phase": phase, **body},
        )


def test_single_use_load_and_input_do_not_approve_or_send(trial, db):
    task = issue(trial)
    assert check(task).json() == {"inputOnly": True, "sendAllowed": False}
    assert check(task).status_code == 409
    assert check(task, "INPUT").status_code == 200
    assert check(task, "INPUT").status_code == 409
    assert settings.outbound_enabled is False
    from app.models import ApprovalRequest, EmailDelivery, FormDelivery

    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    item = db.get(Activity, UUID(task["trialId"]))
    assert "fixture@example.com" not in item.note


@pytest.mark.parametrize(
    "change", ["off", "blocked", "wrong-url", "agent", "confirmed", "missing-terms"]
)
def test_creation_boundaries(trial, db, monkeypatch, change):
    client, company, plan, path = trial
    headers = {}
    if change == "off":
        monkeypatch.setattr(settings, "live_form_input_enabled", False)
    if change == "blocked":
        company.do_not_contact = True
        db.commit()
    if change == "wrong-url":
        plan["formUrl"] = "https://foreign.example/contact"
    if change == "agent":
        headers = {"Authorization": "Bearer agent-credential"}
    if change == "confirmed":
        plan["confirmed"] = True
    if change == "missing-terms":
        plan["termsConfirmed"] = False
    assert client.post(path, json=plan, headers=headers).status_code in {403, 409, 422}


@pytest.mark.parametrize(
    "change", ["blocked", "suppression", "expired", "hash", "tamper", "permissions"]
)
def test_core_revalidation_before_input(trial, db, users, change):
    task = issue(trial)
    assert check(task).status_code == 200
    _, company, _, _ = trial
    item = db.get(Activity, UUID(task["trialId"]))
    if change == "blocked":
        company.do_not_contact = True
    if change == "suppression":
        db.add(
            SuppressionEntry(
                project_id=company.project_id, domain="synthetic.example", reason="Opt out"
            )
        )
    if change == "permissions":
        db.get(Project, company.project_id).user_id = users[1].id
    if change == "expired":
        value = json.loads(item.note[len(PREFIX) :])
        value["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        item.note = stored(item, value)
    if change == "tamper":
        item.note = item.note.replace("synthetic.example", "foreign.example")
    db.commit()
    if change == "hash":
        task["requestHash"] = "0" * 64
    assert check(task, "INPUT").status_code in {401, 404, 409}


def test_revoke_and_cookie_mixing(trial):
    task = issue(trial)
    client, company, _, _ = trial
    assert (
        client.post(
            f"/api/live-input-trials/{task['trialId']}/check",
            headers={"Authorization": f"Bearer {task['token']}"},
            json={"requestHash": task["requestHash"], "phase": "LOAD"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/companies/{company.id}/live-input-trials/{task['trialId']}/revoke"
        ).status_code
        == 200
    )
    assert check(task).status_code == 409


def test_viewer_cannot_issue(trial, db, users):
    client, company, plan, path = trial
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert client.post(path, json=plan).status_code == 404
