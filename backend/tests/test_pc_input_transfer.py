import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Activity, Company, Project, ProjectMember, TargetProfile
from app.pc_input_routes import PREFIX, REPORT_PREFIX, seal


@pytest.fixture
def task(auth, db, users, monkeypatch):
    monkeypatch.setattr(settings, "pc_diagnostic_transfer_enabled", True)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(
        settings, "settings_encryption_key", "TXo8wyai6a-uQTN15jhU7_la86LCSPzFR6pMXGkYslM="
    )
    profile = TargetProfile(user_id=users[0].id, profile_name="Synthetic")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=users[0].id,
        target_profile_id=profile.id,
        project_name="PC diagnostic",
        sales_objective="No send",
        region="test",
    )
    db.add(project)
    db.flush()
    company = Company(
        project_id=project.id, company_name="Synthetic", domain="synthetic.example", source="url"
    )
    db.add(company)
    db.commit()
    binding = dict(
        trialId=str(uuid4()),
        companyId=str(company.id),
        projectId=str(project.id),
        requestHash="a" * 64,
        htmlHash="b" * 64,
    )
    path = f"/api/companies/{company.id}/pc-input-trials"
    return auth, company, binding, path


def issue(task):
    client, _, binding, path = task
    response = client.post(path, json=binding)
    assert response.status_code == 200
    token = response.json()["token"]
    report = dict(
        definition="offline-input-report-v1",
        binding=binding,
        result=dict(
            definition="offline-form-input-v1",
            status="HUMAN_REQUIRED",
            reason="CAPTCHA",
            htmlHash=binding["htmlHash"],
            payloadHash="c" * 64,
            structureHash=None,
            fieldsFilled=0,
            actions=1,
            blockedRequests=0,
            durationMs=10,
            executionAllowed=False,
            approvalGranted=False,
            confirmationReached=False,
            liveFetchPerformed=False,
            sent=False,
        ),
    )
    client.cookies.clear()
    return token, report, f"/api/pc-input-trials/{binding['trialId']}/result"


def test_single_job_write_and_identical_retry(task, db):
    token, report, path = issue(task)
    client, company, binding, _ = task
    header = {"Authorization": f"Bearer {token}"}
    assert client.post(path, headers=header, json=report).json() == dict(
        recorded=True, alreadyRecorded=False
    )
    assert client.post(path, headers=header, json=report).json()["alreadyRecorded"] is True
    rows = db.scalars(select(Activity).where(Activity.company_id == company.id)).all()
    assert len(rows) == 2
    assert token not in "".join(row.note for row in rows)
    recorded = next(row for row in rows if row.note.startswith(REPORT_PREFIX))
    value = json.loads(recorded.note[len(REPORT_PREFIX) :])
    assert value["source"] == "PC_REPORTED_UNVERIFIED"
    assert value["sent"] is False
    report["result"]["reason"] = "REQUIRED_FIELD_UNKNOWN"
    assert client.post(path, headers=header, json=report).status_code == 409
    assert db.get(Activity, binding["trialId"]).note.startswith(PREFIX)
    assert company.do_not_contact is False
    assert settings.outbound_enabled is False


@pytest.mark.parametrize(
    "change",
    [
        "company",
        "project",
        "hash",
        "sent",
        "zero_flag",
        "unknown_reason",
        "extra",
        "cookie",
        "agent",
        "missing",
    ],
)
def test_reporting_rejects_other_scope_or_unsafe_result(task, change):
    token, report, path = issue(task)
    client = task[0]
    header = {"Authorization": f"Bearer {token}"}
    if change == "company":
        report["binding"]["companyId"] = str(uuid4())
    elif change == "project":
        report["binding"]["projectId"] = str(uuid4())
    elif change == "hash":
        report["result"]["htmlHash"] = "d" * 64
    elif change == "sent":
        report["result"]["sent"] = True
    elif change == "zero_flag":
        report["result"]["sent"] = 0
    elif change == "unknown_reason":
        report["result"]["reason"] = "SECRET_SHOULD_NOT_BE_SAVED"
    elif change == "extra":
        report["result"]["body"] = "must not save"
    elif change == "cookie":
        client.cookies.set("leadhive_session", "not-a-session")
    elif change == "agent":
        header = {"Authorization": "Bearer lh_agent_not_a_diagnostic"}
    else:
        header = {}
    assert client.post(path, headers=header, json=report).status_code in {401, 403, 409, 422}


@pytest.mark.parametrize(
    "state",
    ["expired", "revoked", "deleted_issuer", "moved_company", "permission_removed", "disabled"],
)
def test_expiration_revocation_and_current_boundaries(task, db, state, monkeypatch, users):
    token, report, path = issue(task)
    client, company, binding, _ = task
    item = db.get(Activity, binding["trialId"])
    value = json.loads(item.note[len(PREFIX) :])
    if state == "expired":
        value["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    elif state == "revoked":
        value["state"] = "REVOKED"
    elif state == "deleted_issuer":
        value["issuer_id"] = str(uuid4())
    elif state == "moved_company":
        original = db.get(Project, company.project_id)
        destination = Project(
            user_id=users[0].id,
            target_profile_id=original.target_profile_id,
            project_name="Moved",
            sales_objective="No send",
            region="test",
        )
        db.add(destination)
        db.flush()
        company.project_id = destination.id
    elif state == "permission_removed":
        project = db.get(Project, company.project_id)
        project.user_id = users[1].id
        db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    else:
        monkeypatch.setattr(settings, "pc_diagnostic_transfer_enabled", False)
    item.note = seal(item.id, item.company_id, value)
    db.commit()
    assert client.post(
        path, headers={"Authorization": f"Bearer {token}"}, json=report
    ).status_code in {401, 403, 404, 409}


def test_issue_requires_human_project_write_and_default_flag(task, db, users, monkeypatch):
    client, company, binding, path = task
    monkeypatch.setattr(settings, "pc_diagnostic_transfer_enabled", False)
    assert client.post(path, json=binding).status_code == 403
    monkeypatch.setattr(settings, "pc_diagnostic_transfer_enabled", True)
    assert client.post(path, json={**binding, "projectId": str(uuid4())}).status_code == 409
    assert (
        client.post(
            path, headers={"Authorization": "Bearer lh_diag_fake"}, json=binding
        ).status_code
        == 403
    )
    project = db.get(Project, company.project_id)
    project.user_id = users[1].id
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert client.post(path, json=binding).status_code == 404


def test_human_can_revoke(task, db, users):
    client, company, binding, path = task
    response = client.post(path, json=binding)
    token = response.json()["token"]
    revoke = f"/api/companies/{company.id}/pc-input-trials/{binding['trialId']}/revoke"
    assert client.post(revoke).json() == {"revoked": True}
    value = json.loads(db.get(Activity, binding["trialId"]).note[len(PREFIX) :])
    assert value["state"] == "REVOKED"
    client.cookies.clear()
    assert client.post(revoke, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_diagnostic_token_cannot_act_as_human_or_change_company(task):
    token, report, _ = issue(task)
    client, company, _, _ = task
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        client.post(
            f"/api/approval-requests/{uuid4()}/approve",
            headers=headers,
            json={"confirmed": True},
        ).status_code
        == 403
    )

    assert (
        client.patch(
            f"/api/companies/{company.id}/contact-control",
            headers=headers,
            json={"do_not_contact": False},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("field", ["issuer_id", "expires_at", "state", "binding", "token_hash"])
def test_activity_metadata_tampering_is_rejected(task, db, field):
    token, report, path = issue(task)
    item = db.get(Activity, task[2]["trialId"])
    value = json.loads(item.note[len(PREFIX) :])
    value[field] = "tampered"
    item.note = PREFIX + json.dumps(value)
    db.commit()
    assert (
        task[0].post(path, headers={"Authorization": f"Bearer {token}"}, json=report).status_code
        == 401
    )


def test_missing_encryption_key_fails_closed(task, monkeypatch):
    monkeypatch.setattr(settings, "settings_encryption_key", "")
    assert task[0].post(task[3], json=task[2]).status_code == 503


def test_key_rotation_invalidates_existing_capability(task, monkeypatch):
    token, report, path = issue(task)
    monkeypatch.setattr(
        settings, "settings_encryption_key", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    )
    assert (
        task[0].post(path, headers={"Authorization": f"Bearer {token}"}, json=report).status_code
        == 401
    )
