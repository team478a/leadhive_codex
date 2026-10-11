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


def live_report(task):
    return dict(
        definition="live-form-input-only-v1",
        trialId=task["trialId"],
        companyId=task["companyId"],
        projectId=task["projectId"],
        requestHash=task["requestHash"],
        status="LIVE_INPUT_VERIFIED",
        reason="STOP_BEFORE_CONFIRMATION_OR_SEND",
        fieldsFilled=1,
        blockedRequests=0,
        sent=False,
        approvalGranted=False,
        executionAllowed=False,
        confirmationReached=False,
    )


def post_report(task, body):
    with TestClient(app) as pc:
        return pc.post(
            f"/api/live-input-trials/{task['trialId']}/result",
            headers={"Authorization": f"Bearer {task['token']}"},
            json=body,
        )


def auto_task(trial):
    trial[2]["autoReport"] = True
    task = issue(trial)
    assert check(task).status_code == 200
    assert check(task, "INPUT").status_code == 200
    return task


def test_result_atomic_idempotent_read_and_no_secrets(trial, db):
    task = auto_task(trial)
    report = live_report(task)
    assert post_report(task, report).json() == {"recorded": True, "alreadyRecorded": False}
    count = db.scalar(select(func.count()).select_from(Activity))
    assert post_report(task, report).json() == {"recorded": True, "alreadyRecorded": True}
    assert db.scalar(select(func.count()).select_from(Activity)) == count
    assert post_report(task, dict(report, fieldsFilled=2)).status_code == 409
    client, company, _, _ = trial
    response = client.get(f"/api/companies/{company.id}/live-input-trials/{task['trialId']}/result")
    assert response.status_code == 200
    assert response.json()["report"]["source"] == "PC_REPORTED_UNVERIFIED"
    for note in db.scalars(select(Activity.note)):
        assert task["token"] not in note
        assert "fixture@example.com" not in note
    assert check(task).status_code == 409
    assert settings.outbound_enabled is False
    from app.models import ApprovalRequest, EmailDelivery, FormDelivery

    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "change",
    [
        "optout",
        "not-started",
        "revoked",
        "expired",
        "hash",
        "company",
        "project",
        "token",
        "tamper",
        "permissions",
        "sent",
        "approval",
        "confirmation",
        "secret",
        "false-integer",
        "blocked-success",
    ],
)
def test_result_boundaries(trial, db, users, change):
    if change == "optout":
        task = issue(trial)
        assert check(task).status_code == 200
        assert check(task, "INPUT").status_code == 200
    elif change == "not-started":
        trial[2]["autoReport"] = True
        task = issue(trial)
    else:
        task = auto_task(trial)
    body = live_report(task)
    item = db.get(Activity, UUID(task["trialId"]))
    if change in {"revoked", "expired"}:
        value = json.loads(item.note[len(PREFIX) :])
        if change == "revoked":
            value["state"] = "REVOKED"
        else:
            value["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        item.note = stored(item, value)
    if change == "tamper":
        item.note = item.note.replace("synthetic.example", "foreign.example")
    if change == "permissions":
        db.get(Project, trial[1].project_id).user_id = users[1].id
    if change == "hash":
        body["requestHash"] = "0" * 64
    if change == "company":
        body["companyId"] = "00000000-0000-0000-0000-000000000000"
    if change == "project":
        body["projectId"] = "00000000-0000-0000-0000-000000000000"
    if change == "token":
        task["token"] = "lh_input_" + "0" * 64
    if change == "sent":
        body["sent"] = True
    if change == "approval":
        body["approvalGranted"] = True
    if change == "confirmation":
        body["confirmationReached"] = 0
    if change == "secret":
        body["values"] = {"email": "fixture@example.com"}
    if change == "false-integer":
        body["fieldsFilled"] = True
    if change == "blocked-success":
        body["blockedRequests"] = 1
    db.commit()
    assert post_report(task, body).status_code in {401, 403, 404, 409, 422}


def test_result_cookie_and_project_boundary(trial, db, users):
    task = auto_task(trial)
    client, company, _, _ = trial
    assert (
        client.post(
            f"/api/live-input-trials/{task['trialId']}/result",
            json=live_report(task),
            headers={"Authorization": f"Bearer {task['token']}"},
        ).status_code
        == 403
    )
    assert post_report(task, live_report(task)).status_code == 200
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    path = f"/api/companies/{company.id}/live-input-trials/{task['trialId']}/result"
    assert client.get(path).status_code == 404
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert client.get(path).status_code == 200


def test_result_tampered_activity_rejected(trial, db):
    task = auto_task(trial)
    assert post_report(task, live_report(task)).status_code == 200
    result = db.scalar(select(Activity).where(Activity.note.startswith("実ページ入力報告 v1: ")))
    result.note = result.note.replace('"fieldsFilled":1', '"fieldsFilled":2')
    db.commit()
    assert (
        trial[0]
        .get(f"/api/companies/{trial[1].id}/live-input-trials/{task['trialId']}/result")
        .status_code
        == 409
    )
