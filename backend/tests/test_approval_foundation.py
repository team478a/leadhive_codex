"""A2 security tests against real PostgreSQL. No delivery/network execution."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.model_approval import (
    AgentCredential,
    AgentIdentity,
    AgentProjectGrant,
    ApprovalRequest,
    HumanApprovalProof,
    OutreachAuditEvent,
)
from app.models import (
    AuthSession,
    Company,
    EmailDelivery,
    FormDelivery,
    FormProfile,
    FormProfileField,
    OutreachDraft,
    Project,
    ProjectMember,
    TargetProfile,
    User,
)
from app.schema_approval import Approve
from app.security import COOKIE_NAME, token_digest
from app.services import human_approval as service
from tests.conftest import PASSWORD


@pytest.fixture
def workspace(db, users):
    profile = TargetProfile(user_id=users[0].id, profile_name="A2 profile")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=users[0].id,
        project_name="A2 project",
        target_profile_id=profile.id,
        sales_objective="Approval foundation",
        region="全国",
    )
    db.add(project)
    db.flush()
    company = Company(
        source="url",
        project_id=project.id,
        company_name="Test Company",
        website_url="https://approval.example",
        domain="approval.example",
    )
    db.add(company)
    db.commit()
    return project, company


def proposal(company):
    return {
        "company_id": str(company.id),
        "channel": "email",
        "delivery_method": "email",
        "recipient": "recipient@example.com",
        "subject": "A2 subject",
        "body": "A2 body",
        "sender": {"name": "Human", "email": "sender@example.com"},
    }


def create(auth, workspace, **overrides):
    project, company = workspace
    result = auth.post(
        f"/api/projects/{project.id}/approval-requests", json=proposal(company) | overrides
    )
    assert result.status_code == 201, result.text
    return result.json()


def expected(item):
    return {"expected_hash": item["payload_hash"], "expected_version": item["payload_version"]}


def challenge(auth, item, verify=True):
    result = auth.post(f"/api/approval-requests/{item['id']}/challenge", json=expected(item))
    assert result.status_code == 200, result.text
    token = result.json()["challenge_token"]
    if verify:
        result = auth.post(
            f"/api/approval-requests/{item['id']}/challenge/verify",
            json={"challenge_token": token, "password": PASSWORD},
        )
        assert result.status_code == 200, result.text
    return token


def approve(auth, item, token):
    return auth.post(
        f"/api/approval-requests/{item['id']}/approve",
        json=expected(item) | {"challenge_token": token},
    )


def agent_token(auth, workspace, scopes=None):
    result = auth.post(
        f"/api/projects/{workspace[0].id}/agents",
        json={"name": "Test Agent", "scopes": scopes or ["outreach:prepare", "outreach:read"]},
    )
    assert result.status_code == 201, result.text
    return result.json()


@pytest.mark.parametrize("action", ["approve", "reject", "revoke", "challenge", "challenge/verify"])
def test_agent_cannot_make_human_decisions(auth, workspace, monkeypatch, action, db):
    monkeypatch.setattr(settings, "agent_features_enabled", True)
    item = create(auth, workspace)
    issued = agent_token(auth, workspace)
    auth.cookies.clear()
    body = expected(item) | {"challenge_token": "x" * 43, "reason": "agent", "confirmed": True}
    result = auth.post(
        f"/api/approval-requests/{item['id']}/{action}",
        json=body,
        headers={"Authorization": f"Bearer {issued['token']}"},
    )
    assert result.status_code == 403
    assert db.get(ApprovalRequest, item["id"]).status == "PENDING"


@pytest.mark.parametrize(
    "scope",
    [
        "outreach:approve",
        "email:send",
        "form:send",
        "suppression:remove",
        "optout:remove",
        "credentials:read",
        "credentials:update",
        "user:manage",
        "destructive:delete",
        "unknown",
    ],
)
def test_scope_issuance_rejects_unknown_and_forbidden(auth, workspace, scope):
    assert (
        auth.post(
            f"/api/projects/{workspace[0].id}/agents", json={"name": "Agent", "scopes": [scope]}
        ).status_code
        == 422
    )


def test_agent_feature_cookie_scope_and_project_boundaries(auth, workspace, monkeypatch, db):
    issued = agent_token(auth, workspace)
    headers = {"Authorization": f"Bearer {issued['token']}"}
    path = f"/api/agent/projects/{workspace[0].id}/approval-requests"
    assert auth.post(path, json=proposal(workspace[1]), headers=headers).status_code == 403
    assert (
        auth.get("/api/health", headers=headers).status_code == 403
    )  # Mixed even on public routes.
    auth.cookies.clear()
    assert auth.post(path, json=proposal(workspace[1]), headers=headers).status_code == 403
    monkeypatch.setattr(settings, "agent_features_enabled", True)
    assert auth.post(path, json=proposal(workspace[1]), headers=headers).status_code == 201
    assert auth.get(path, headers=headers).json()[0]["created_by_principal_type"] == "AGENT"
    assert (
        auth.post(
            f"/api/agent/projects/{uuid4()}/approval-requests",
            json=proposal(workspace[1]),
            headers=headers,
        ).status_code
        == 403
    )
    credential = db.scalar(select(AgentCredential))
    credential.scopes = ["outreach:read"]
    db.commit()
    assert auth.post(path, json=proposal(workspace[1]), headers=headers).status_code == 403
    assert auth.get(path, headers=headers).status_code == 200
    assert issued["token"] not in json.dumps(
        [row.reason for row in db.scalars(select(OutreachAuditEvent))]
    )
    assert credential.token_hash != issued["token"]


@pytest.mark.parametrize("path", ["/api/projects", "/api/admin/smtp-settings", "/api/auth/login"])
def test_agent_cannot_use_legacy_human_routes(auth, workspace, path):
    issued = agent_token(auth, workspace)
    auth.cookies.clear()
    headers = {"Authorization": f"Bearer {issued['token']}"}
    result = (
        auth.post(path, headers=headers, json={"email": "user0@example.com", "password": PASSWORD})
        if path.endswith("login")
        else auth.get(path, headers=headers)
    )
    assert result.status_code == 403


@pytest.mark.parametrize("action", ["approve", "reject", "revoke", "challenge"])
def test_viewer_and_other_project_denied(auth, workspace, users, db, action):
    item = create(auth, workspace)
    auth.cookies.clear()
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    path = f"/api/approval-requests/{item['id']}/{action}"
    data = expected(item)
    if action == "approve":
        data["challenge_token"] = "x" * 43
    elif action in {"reject", "revoke"}:
        data["reason"] = "test"
    assert auth.post(path, json=data).status_code == 404
    db.add(ProjectMember(project_id=workspace[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(f"/api/approval-requests/{item['id']}").status_code == 200
    assert auth.post(path, json=data).status_code == 404


@pytest.mark.parametrize("member", [False, True])
def test_only_human_with_bound_step_up_can_approve(auth, workspace, users, db, member):
    item = create(auth, workspace)
    if member:
        db.add(ProjectMember(project_id=workspace[0].id, user_id=users[1].id, role="editor"))
        db.commit()
        auth.cookies.clear()
        auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert approve(auth, item, "x" * 43).status_code == 403
    token = challenge(auth, item, verify=False)
    assert approve(auth, item, token).status_code == 403
    assert (
        auth.post(
            f"/api/approval-requests/{item['id']}/challenge/verify",
            json={"challenge_token": token, "password": PASSWORD},
        ).status_code
        == 200
    )
    response = approve(auth, item, token)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "APPROVED"
    assert result["approved_by_user_id"] == str(users[int(member)].id)
    assert result["approved_payload_hash"] == item["payload_hash"]
    assert result["approved_payload_version"] == 1
    assert approve(auth, item, token).status_code == 409
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == 0
    assert db.scalar(
        select(OutreachAuditEvent).where(OutreachAuditEvent.event == "approval granted")
    )


@pytest.mark.parametrize(
    "fault",
    [
        "expired",
        "wrong_session",
        "wrong_request",
        "wrong_password",
        "replay_verify",
        "hash",
        "version",
    ],
)
def test_step_up_rejects_binding_expiry_and_replay(auth, workspace, db, monkeypatch, fault):
    item = create(auth, workspace)
    token = challenge(auth, item)
    if fault == "expired":
        clock = service.now()
        monkeypatch.setattr(service, "now", lambda: clock + timedelta(minutes=6))
    elif fault == "wrong_session":
        auth.post("/api/auth/login", json={"email": "user0@example.com", "password": PASSWORD})
    elif fault == "wrong_request":
        item = create(auth, workspace)
    elif fault in {"wrong_password", "replay_verify"}:
        if fault == "wrong_password":
            token = challenge(auth, item, verify=False)
        result = auth.post(
            f"/api/approval-requests/{item['id']}/challenge/verify",
            json={
                "challenge_token": token,
                "password": "wrong" if fault == "wrong_password" else PASSWORD,
            },
        )
        assert result.status_code in {403, 409}
        if fault == "replay_verify":
            return
    data = expected(item) | {"challenge_token": token}
    if fault == "hash":
        data["expected_hash"] = "0" * 64
    if fault == "version":
        data["expected_version"] = 2
    assert auth.post(f"/api/approval-requests/{item['id']}/approve", json=data).status_code in {
        403,
        409,
    }


@pytest.mark.parametrize("approved", [False, True])
def test_expiration(auth, workspace, monkeypatch, approved):
    item = create(auth, workspace)
    if approved:
        assert approve(auth, item, challenge(auth, item)).status_code == 200
    clock = service.now()
    monkeypatch.setattr(service, "now", lambda: clock + timedelta(hours=25))
    result = auth.get(f"/api/approval-requests/{item['id']}")
    assert result.json()["status"] == "EXPIRED"
    assert (
        auth.post(f"/api/approval-requests/{item['id']}/challenge", json=expected(item)).status_code
        == 409
    )


@pytest.mark.parametrize("action", ["reject", "revoke"])
def test_human_decisions_and_revision_invalidate_approval(auth, workspace, action, db):
    first = create(auth, workspace)
    assert (
        auth.post(
            f"/api/approval-requests/{first['id']}/{action}",
            json=expected(first) | {"reason": "human reason"},
        ).status_code
        == 200
    )
    old = create(auth, workspace)
    assert approve(auth, old, challenge(auth, old)).status_code == 200
    data = proposal(workspace[1]) | expected(old) | {"body": "changed body"}
    new = auth.post(f"/api/approval-requests/{old['id']}/revisions", json=data)
    assert new.status_code == 201, new.text
    assert new.json()["payload_version"] == 2
    assert new.json()["payload_hash"] != old["payload_hash"]
    assert new.json()["status"] == "PENDING"
    assert auth.get(f"/api/approval-requests/{old['id']}").json()["status"] == "REVOKED"
    assert not service.valid_approved_payload(db, db.get(ApprovalRequest, old["id"]))
    assert auth.post(f"/api/approval-requests/{old['id']}/revisions", json=data).status_code == 409


def test_source_draft_change_revokes_old_approval(auth, workspace, db):
    draft = OutreachDraft(
        company_id=workspace[1].id,
        channel="email",
        subject="A2 subject",
        body="A2 body",
        ai_model="test",
        ai_provider="test",
    )
    db.add(draft)
    db.commit()
    item = create(auth, workspace, source_draft_id=str(draft.id))
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    draft.body = "Changed after approval"
    db.commit()
    result = auth.get(f"/api/approval-requests/{item['id']}")
    assert result.json()["status"] == "REVOKED"
    assert result.json()["invalidation_reason"] == "source draft changed"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE outreach_audit_events SET reason='tamper'",
        "DELETE FROM outreach_audit_events",
        "TRUNCATE outreach_audit_events",
        "UPDATE approval_requests SET body='tamper'",
        "UPDATE approval_requests SET payload_version=2",
        "DELETE FROM approval_requests",
        "UPDATE approval_requests SET status='CONSUMED'",
    ],
)
def test_database_guards_immutable_records(auth, workspace, db, sql):
    create(auth, workspace)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(sql))


def test_ledger_same_transaction_and_no_secrets(auth, workspace, db, monkeypatch):
    item = create(auth, workspace)
    token = challenge(auth, item)
    original = service.audit

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(service, "audit", fail)
    with pytest.raises(RuntimeError):
        service.approve(
            db,
            db.get(ApprovalRequest, item["id"]),
            Approve(**expected(item), challenge_token=token),
            db.get(
                User,
                db.scalar(select(AuthSession.user_id)),
            ),
            token_digest(auth.cookies.get(COOKIE_NAME)),
        )
    db.rollback()
    assert db.get(ApprovalRequest, item["id"]).status == "PENDING"
    assert (
        db.scalar(
            select(HumanApprovalProof).where(HumanApprovalProof.request_id == item["id"])
        ).used_at
        is None
    )
    ledger = auth.get(f"/api/projects/{workspace[0].id}/approval-audit").text
    assert PASSWORD not in ledger and token not in ledger and "A2 body" not in ledger


def test_strict_fields_expiry_limits_and_ledger_api(auth, workspace):
    for extra in [
        {"confirmed": True},
        {"status": "APPROVED"},
        {"expires_in_hours": 25},
        {"expires_in_hours": 0},
        {"approved_by_user_id": str(uuid4())},
    ]:
        assert (
            auth.post(
                f"/api/projects/{workspace[0].id}/approval-requests",
                json=proposal(workspace[1]) | extra,
            ).status_code
            == 422
        )
    item = create(auth, workspace)
    for method in ["put", "patch", "delete"]:
        assert (
            getattr(auth, method)(f"/api/projects/{workspace[0].id}/approval-audit").status_code
            == 405
        )
    for _ in range(5):
        challenge(auth, item, verify=False)
    assert (
        auth.post(f"/api/approval-requests/{item['id']}/challenge", json=expected(item)).status_code
        == 429
    )


@pytest.mark.parametrize(
    "fault",
    [
        "credential_revoked",
        "credential_expired",
        "identity_disabled",
        "grant_revoked",
        "unknown_scope",
    ],
)
def test_agent_credential_lifecycle(auth, workspace, db, monkeypatch, fault):
    monkeypatch.setattr(settings, "agent_features_enabled", True)
    issued = agent_token(auth, workspace)
    credential = db.get(AgentCredential, issued["credential_id"])
    grant = db.scalar(select(AgentProjectGrant))
    if fault == "credential_revoked":
        credential.revoked = True
    elif fault == "credential_expired":
        credential.expires_at = service.now() - timedelta(minutes=1)
    elif fault == "identity_disabled":
        db.get(AgentIdentity, issued["agent_id"]).active = False
    elif fault == "grant_revoked":
        grant.active = False
    else:
        grant.scopes = ["outreach:prepare", "outreach:read", "email:send"]
    db.commit()
    auth.cookies.clear()
    result = auth.get(
        f"/api/agent/projects/{workspace[0].id}/approval-requests",
        headers={"Authorization": f"Bearer {issued['token']}"},
    )
    assert result.status_code in {401, 403}


def test_agent_revision_returns_pending_and_revokes_human_approval(
    auth, workspace, db, monkeypatch
):
    monkeypatch.setattr(settings, "agent_features_enabled", True)
    old = create(auth, workspace)
    assert approve(auth, old, challenge(auth, old)).status_code == 200
    issued = agent_token(auth, workspace)
    auth.cookies.clear()
    headers = {"Authorization": f"Bearer {issued['token']}"}
    result = auth.post(
        f"/api/agent/projects/{workspace[0].id}/approval-requests/{old['id']}/revisions",
        json=proposal(workspace[1]) | expected(old) | {"recipient": "new@example.com"},
        headers=headers,
    )
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "PENDING"
    assert result.json()["payload_version"] == 2
    assert not service.valid_approved_payload(db, db.get(ApprovalRequest, old["id"]))


def test_form_snapshot_requires_no_network(auth, workspace):
    item = create(
        auth,
        workspace,
        channel="form",
        delivery_method="form_codex",
        recipient=None,
        form_url="https://approval.example/contact",
        field_values={"email": "sender@example.com", "message": "A2 form body"},
    )
    assert item["payload_snapshot"]["field_values"]["message"] == "A2 form body"
    assert approve(auth, item, challenge(auth, item)).json()["status"] == "APPROVED"


def test_proof_is_bound_to_user_and_role_is_rechecked(auth, workspace, users, db):
    item = create(auth, workspace)
    token = challenge(auth, item)
    member = ProjectMember(project_id=workspace[0].id, user_id=users[1].id, role="editor")
    db.add(member)
    db.commit()
    auth.cookies.clear()
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert approve(auth, item, token).status_code == 403
    token = challenge(auth, item)
    member.role = "viewer"
    db.commit()
    assert approve(auth, item, token).status_code == 404


def test_approved_proof_cannot_be_changed_even_after_revocation(auth, workspace, db):
    item = create(auth, workspace)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    auth.post(
        f"/api/approval-requests/{item['id']}/revoke", json=expected(item) | {"reason": "revoke"}
    )
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text("UPDATE approval_requests SET approved_payload_hash='tamper'"))


@pytest.mark.parametrize(
    "suffix,payload",
    [
        ("email-delivery", {"recipient_email": "recipient@example.com", "confirmed": True}),
        (
            "form-delivery",
            {"form_url": "https://approval.example/contact", "field_values": {}, "confirmed": True},
        ),
        ("form-assist-delivery", {"status": "submitted", "confirmed": True}),
    ],
)
def test_legacy_confirmed_never_bypasses_agent_guard(auth, workspace, db, suffix, payload):
    issued = agent_token(auth, workspace)
    auth.cookies.clear()
    result = auth.post(
        f"/api/outreach-drafts/{uuid4()}/{suffix}",
        json=payload,
        headers={"Authorization": f"Bearer {issued['token']}"},
    )
    assert result.status_code == 403
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == 0


def test_company_target_change_invalidates_old_approval(auth, workspace, db):
    item = create(auth, workspace)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    workspace[1].email = "changed@example.com"
    db.commit()
    result = auth.get(f"/api/approval-requests/{item['id']}").json()
    assert result["status"] == "REVOKED"
    assert result["invalidation_reason"] == "company target changed"


@pytest.mark.parametrize("change", ["fingerprint", "mapping"])
def test_form_profile_change_invalidates_old_approval(auth, workspace, db, change):
    profile = FormProfile(
        company_id=workspace[1].id,
        form_url="https://approval.example/contact",
        fingerprint="a" * 64,
    )
    db.add(profile)
    db.flush()
    field = FormProfileField(
        form_profile_id=profile.id, position=0, field_type="text", mapped_key="name"
    )
    db.add(field)
    db.commit()
    item = create(
        auth,
        workspace,
        channel="form",
        delivery_method="form_direct",
        recipient=None,
        form_url=profile.form_url,
    )
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    if change == "fingerprint":
        profile.fingerprint = "b" * 64
    else:
        field.mapped_key = "email"
    db.commit()
    result = auth.get(f"/api/approval-requests/{item['id']}").json()
    assert result["status"] == "REVOKED"
    assert result["invalidation_reason"] == "form profile or mapping changed"
