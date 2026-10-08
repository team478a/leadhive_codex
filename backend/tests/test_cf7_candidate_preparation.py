"""P2 API and PostgreSQL security tests, controlled evidence only, no sends."""

import copy
import importlib.util
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    CF7Observation,
    FormDelivery,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachAuditEvent,
    OutreachDraft,
    ProjectMember,
    SuppressionEntry,
)
from app.services import cf7_candidate_preparation as service
from app.services import human_approval as approval
from app.services.cf7_candidate_contract import digest
from tests.test_approval_foundation import approve, challenge, expected, proposal
from tests.test_approval_foundation import workspace as workspace
from tests.test_cf7_candidate_contract import candidate


@pytest.fixture
def source(db, workspace, users, monkeypatch):
    monkeypatch.setattr(settings, "cf7_candidate_preparation_enabled", True)
    project, company = workspace
    raw = candidate().model_dump(mode="json")
    company.contact_url = raw["form_url"]
    profile = FormProfile(
        company_id=company.id,
        form_url=raw["form_url"],
        fingerprint=raw["dom_fingerprint"],
        form_status="REVIEW_REQUIRED",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        form_found=True,
        confirmation_page=False,
        delivery_supported=False,
        is_primary=True,
        review_reason="CF7候補・送信未接続",
    )
    draft = OutreachDraft(
        company_id=company.id, channel="form", subject="", body="Fixture 日本語\nbody"
    )
    sender = FormSenderSettings(id=1, contact_name="Operator", email="operator@example.com")
    db.add_all([profile, draft, sender])
    db.flush()
    db.add(
        FormProfileField(
            form_profile_id=profile.id,
            position=0,
            name="your-message",
            field_type="textarea",
            label="Message",
            mapped_key="message",
        )
    )
    db.flush()
    structure = {k: raw[k] for k in service.CF7Structure.model_fields}
    evidence = {
        "structure": structure,
        "profile_source_hash": service.profile_source_hash(db, profile),
    }
    observed = approval.now()
    observation = CF7Observation(
        project_id=project.id,
        company_id=company.id,
        form_profile_id=profile.id,
        source_kind="CONTROLLED_FIXTURE",
        observer_version="cf7-controlled-v1",
        observed_at=observed,
        expires_at=observed + timedelta(hours=1),
        evidence_snapshot=evidence,
        evidence_hash=digest(evidence),
        created_by_user_id=users[0].id,
    )
    db.add(observation)
    db.commit()
    return project, company, draft, profile, sender, observation


def url(source, suffix):
    return f"/api/outreach-drafts/{source[2].id}/cf7-candidate-{suffix}"


def preview(auth, source, choices=None):
    return auth.post(
        url(source, "preview"),
        json={"selections": choices or [{"name": "consent", "checked": True}]},
    )


def prepare(auth, source):
    result = preview(auth, source)
    assert result.status_code == 200, result.text
    response = auth.post(
        url(source, "request"),
        json={
            "selections": [{"name": "consent", "checked": True}],
            "expected_preparation_hash": result.json()["preparation_hash"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_human_stepup_approval_and_revoke_without_execution(auth, source, db, monkeypatch):
    import smtplib

    import httpx

    def no_network(*args, **kwargs):
        pytest.fail("outbound transport called during candidate preparation")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    monkeypatch.setattr(smtplib, "SMTP", no_network)
    monkeypatch.setattr(smtplib, "SMTP_SSL", no_network)
    assert auth.get("/api/cf7-candidate-preparation-status").json()["non_executable"]
    initial = auth.get(url(source, "preview"))
    assert initial.status_code == 200 and initial.json()["preparation_hash"] is None
    item = prepare(auth, source)
    row = db.get(ApprovalRequest, item["id"])
    assert row.expires_at == source[5].expires_at
    assert service.valid_request(db, row)
    assert approve(auth, item, challenge(auth, item, verify=False)).status_code == 403
    token = challenge(auth, item)
    assert approve(auth, item, token).json()["status"] == "APPROVED"
    assert approve(auth, item, token).status_code == 409
    assert (
        auth.post(
            f"/api/approval-requests/{item['id']}/form-dispatch",
            json=expected(item) | {"idempotency_key": str(uuid4())},
        ).status_code
        == 409
    )
    assert (
        auth.post(
            f"/api/approval-requests/{item['id']}/revoke",
            json=expected(item) | {"reason": "cancel"},
        ).json()["status"]
        == "REVOKED"
    )
    assert not db.scalar(
        select(ApprovedFormDispatch.id).where(ApprovedFormDispatch.company_id == source[1].id)
    )
    assert not db.scalar(select(FormDelivery.id).where(FormDelivery.company_id == source[1].id))
    assert source[3].form_status == "REVIEW_REQUIRED" and not source[3].delivery_supported
    events = db.scalars(
        select(OutreachAuditEvent).where(OutreachAuditEvent.request_id == row.id)
    ).all()
    assert {e.event for e in events} >= {"proposal created", "approval granted", "revoked"}
    assert all(e.reason is None or "Fixture" not in e.reason for e in events)


@pytest.mark.parametrize(
    "change", ["body", "sender", "profile", "field", "dnc", "suppression", "observation"]
)
def test_source_changes_revoke_approved_request(auth, source, db, change, users):
    item = prepare(auth, source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    if change == "body":
        source[2].body += " changed"
    elif change == "sender":
        source[4].contact_name += " changed"
    elif change == "profile":
        source[3].last_analyzed_at = approval.now()
    elif change == "field":
        field = db.scalar(
            select(FormProfileField).where(FormProfileField.form_profile_id == source[3].id)
        )
        field.label = "Changed consent"
    elif change == "dnc":
        source[1].do_not_contact = True
    elif change == "suppression":
        db.add(
            SuppressionEntry(project_id=source[0].id, domain="managed.example", reason="opt-out")
        )
    else:
        old = source[5]
        db.add(
            CF7Observation(
                project_id=old.project_id,
                company_id=old.company_id,
                form_profile_id=old.form_profile_id,
                source_kind=old.source_kind,
                observer_version=old.observer_version,
                observed_at=approval.now(),
                expires_at=old.expires_at,
                evidence_snapshot=old.evidence_snapshot,
                evidence_hash=old.evidence_hash,
                created_by_user_id=users[0].id,
            )
        )
    db.commit()
    result = auth.get(f"/api/approval-requests/{item['id']}")
    assert result.status_code == 200 and result.json()["status"] == "REVOKED"
    assert not service.valid_request(db, db.get(ApprovalRequest, item["id"]))


@pytest.mark.parametrize(
    "choices",
    [
        [],
        [{"name": "consent", "checked": False}],
        [{"name": "unknown", "checked": True}],
        [{"name": "consent", "checked": True}] * 2,
    ],
)
def test_invalid_consent_cannot_prepare(auth, source, choices):
    assert auth.post(url(source, "preview"), json={"selections": choices}).status_code == 409


@pytest.mark.parametrize(
    "extra", ["body", "form_url", "sender", "hidden", "confirmed", "expires_at"]
)
def test_no_caller_payload_overrides(auth, source, extra):
    assert (
        auth.post(
            url(source, "preview"),
            json={
                "selections": [{"name": "consent", "checked": True}],
                extra: "override",
            },
        ).status_code
        == 422
    )


def test_stale_preview_and_disabled_or_non_test_environment(auth, source, db, monkeypatch):
    data = preview(auth, source).json()
    source[2].body += "new"
    db.commit()
    assert (
        auth.post(
            url(source, "request"),
            json={
                "selections": [{"name": "consent", "checked": True}],
                "expected_preparation_hash": data["preparation_hash"],
            },
        ).status_code
        == 409
    )
    monkeypatch.setattr(settings, "cf7_candidate_preparation_enabled", False)
    assert auth.get(url(source, "preview")).status_code == 409
    monkeypatch.setattr(settings, "cf7_candidate_preparation_enabled", True)
    monkeypatch.setattr(service, "test_database", lambda: False)
    assert auth.get(url(source, "preview")).status_code == 409


def test_expiration_reject_and_bulk_or_revision_denial(auth, source, db, monkeypatch):
    item = prepare(auth, source)
    assert (
        auth.post(
            f"/api/projects/{source[0].id}/bulk-approval/challenge",
            json={"items": [{"request_id": item["id"], **expected(item)}]},
        ).status_code
        == 409
    )
    body = proposal(source[1]) | expected(item)
    assert auth.post(f"/api/approval-requests/{item['id']}/revisions", json=body).status_code == 409
    assert (
        auth.post(
            f"/api/approval-requests/{item['id']}/reject",
            json=expected(item) | {"reason": "reject"},
        ).json()["status"]
        == "REJECTED"
    )
    second = prepare(auth, source)
    monkeypatch.setattr(approval, "now", lambda: source[5].expires_at + timedelta(seconds=1))
    assert auth.get(f"/api/approval-requests/{second['id']}").json()["status"] == "EXPIRED"


def test_agent_mixed_cookie_viewer_and_other_project_denied(auth, source, db, users):
    item = prepare(auth, source)
    assert (
        auth.get(url(source, "preview"), headers={"Authorization": "Bearer fake"}).status_code
        == 403
    )
    assert (
        auth.post(
            f"/api/approval-requests/{item['id']}/approve",
            headers={"Authorization": "Bearer fake"},
            json=expected(item) | {"confirmed": True},
        ).status_code
        == 403
    )
    from tests.conftest import PASSWORD

    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert auth.get(url(source, "preview")).status_code == 404
    db.add(ProjectMember(project_id=source[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(url(source, "preview")).status_code == 404
    assert (
        auth.post(f"/api/approval-requests/{item['id']}/challenge", json=expected(item)).status_code
        == 404
    )


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE cf7_observations SET observer_version='changed'",
        "DELETE FROM cf7_observations",
        "TRUNCATE cf7_observations",
    ],
)
def test_observation_append_only(db, source, sql):
    with pytest.raises(IntegrityError, match="append only"), db.begin_nested():
        db.execute(text(sql))


def test_tampered_outer_or_inner_even_with_recomputed_hash_not_valid(auth, source, db):
    item = prepare(auth, source)
    row = db.get(ApprovalRequest, item["id"])
    # Detached copy simulates corruption without disabling DB immutability.
    for name in ("form_action_url", "cf7_candidate_snapshot_hash", "subject"):
        changed = SimpleNamespace(
            **{c.name: getattr(row, c.name) for c in ApprovalRequest.__table__.columns}
        )
        changed.payload_snapshot = copy.deepcopy(row.payload_snapshot)
        changed.payload_snapshot[name] = "changed"
        changed.payload_hash = approval.payload_hash(changed.payload_snapshot)
        assert not service.valid_request(db, changed)


@pytest.mark.parametrize("change", ["sales", "captcha", "confirmation", "delivery_supported"])
def test_unsafe_or_executable_profile_cannot_prepare(auth, source, db, change):
    profile = source[3]
    if change == "sales":
        profile.sales_contact_status = "PROHIBITED"
    elif change == "captcha":
        profile.captcha_type = "CAPTCHA_RECAPTCHA"
    elif change == "confirmation":
        profile.confirmation_page = True
    else:
        profile.delivery_supported = True
    db.commit()
    assert preview(auth, source).status_code == 409


def test_editor_can_approve_but_payload_hash_version_and_proof_expiry_bound(
    auth, source, db, users, monkeypatch
):
    from tests.conftest import PASSWORD

    db.add(ProjectMember(project_id=source[0].id, user_id=users[1].id, role="editor"))
    db.commit()
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    item = prepare(auth, source)
    token = challenge(auth, item)
    for changes in ({"expected_hash": "f" * 64}, {"expected_version": 2}):
        assert (
            auth.post(
                f"/api/approval-requests/{item['id']}/approve",
                json={
                    **expected(item),
                    "challenge_token": token,
                    **changes,
                },
            ).status_code
            == 409
        )
    clock = approval.now()
    monkeypatch.setattr(approval, "now", lambda: clock + timedelta(minutes=6))
    assert approve(auth, item, token).status_code == 403
    monkeypatch.setattr(approval, "now", lambda: clock)
    assert approve(auth, item, challenge(auth, item)).status_code == 200


def test_observation_ownership_and_downgrade_protection(db, source):
    old = source[5]
    values = {c.name: getattr(old, c.name) for c in CF7Observation.__table__.columns}
    values.update(id=uuid4(), project_id=uuid4())
    with pytest.raises(IntegrityError, match="ownership mismatch"), db.begin_nested():
        db.execute(CF7Observation.__table__.insert().values(**values))
    path = (
        Path(__file__).resolve().parents[1] / "migrations/versions/0152bc1f7548_cf7_observations.py"
    )
    spec = importlib.util.spec_from_file_location("cf7_observation_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(IntegrityError, match="downgrade forbidden"), db.begin_nested():
        with Operations.context(MigrationContext.configure(db.connection())):
            module.downgrade()
    assert db.scalar(text("SELECT to_regclass('cf7_observations')"))


def test_choice_boolean_is_strict_and_optional_subscription_stays_unchecked(auth, source, db):
    assert (
        auth.post(
            url(source, "preview"),
            json={
                "selections": [{"name": "consent", "checked": "true"}],
            },
        ).status_code
        == 422
    )
    old = source[5]
    data = copy.deepcopy(old.evidence_snapshot)
    data["structure"]["controls"].append(
        {
            "name": "newsletter",
            "kind": "checkbox",
            "required": False,
            "label": "Subscribe",
            "checkbox_value": "1",
        }
    )
    db.add(
        CF7Observation(
            project_id=old.project_id,
            company_id=old.company_id,
            form_profile_id=old.form_profile_id,
            source_kind=old.source_kind,
            observer_version=old.observer_version,
            observed_at=approval.now(),
            expires_at=old.expires_at,
            evidence_snapshot=data,
            evidence_hash=digest(data),
            created_by_user_id=old.created_by_user_id,
        )
    )
    db.commit()
    response = preview(
        auth,
        source,
        [{"name": "consent", "checked": True}, {"name": "newsletter", "checked": False}],
    )
    assert response.status_code == 200, response.text
    contract = response.json()["cf7_candidate_snapshot"]["contract"]
    assert "newsletter" not in {v["name"] for v in contract["field_values"]}
    assert contract["selections"][-1] == {"name": "newsletter", "checked": False}
