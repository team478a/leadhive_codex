"""Stored-data preparation and approval invalidation; no external requests."""

import pytest
from sqlalchemy import func, select

from app.models import (
    FormDelivery,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
)
from tests.test_approval_foundation import (
    approve,  # noqa: F401
    challenge,
    expected,
)
from tests.test_approval_foundation import workspace as workspace


@pytest.fixture
def form_source(db, workspace):
    project, company = workspace
    company.contact_url = "https://approval.example/contact"
    sender = FormSenderSettings(id=1, contact_name="担当者", email="sender@example.com")
    db.add(sender)
    profile = FormProfile(
        company_id=company.id,
        form_url=company.contact_url,
        form_status="READY",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        form_found=True,
        delivery_supported=True,
        fingerprint="a" * 64,
        is_primary=True,
    )
    db.add(profile)
    db.flush()
    fields = [
        FormProfileField(
            form_profile_id=profile.id,
            position=position,
            name=name,
            label=name,
            field_type=kind,
            required=True,
            mapped_key=key,
        )
        for position, (name, kind, key) in enumerate(
            [
                ("email", "email", "email"),
                ("message", "textarea", "message"),
            ]
        )
    ]
    db.add_all(fields)
    draft = OutreachDraft(company_id=company.id, channel="form", subject="提案", body="営業文面")
    db.add(draft)
    db.commit()
    return project, company, draft, profile, sender, fields


def preview(auth, source):
    result = auth.get(f"/api/outreach-drafts/{source[2].id}/form-approval-preview")
    assert result.status_code == 200, result.text
    return result.json()


def prepare(auth, source):
    data = preview(auth, source)
    result = auth.post(
        f"/api/outreach-drafts/{source[2].id}/form-approval-request",
        json={
            "expected_preparation_hash": data["preparation_hash"],
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_preparation_approval_never_delivers(auth, form_source, db, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Preparation must not fetch or submit")

    monkeypatch.setattr("app.services.form_delivery.inspect_form", forbidden)
    monkeypatch.setattr("app.services.form_delivery.submit_form", forbidden)
    item = prepare(auth, form_source)
    assert item["field_values"] == {"email": "sender@example.com", "message": "営業文面"}
    assert item["status"] == "PENDING"
    assert (
        auth.post(f"/api/approval-requests/{item['id']}/approve", json=expected(item)).status_code
        == 422
    )
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == 0


@pytest.mark.parametrize("change", ["sender", "draft", "mapping", "profile"])
def test_changed_inputs_require_refresh_and_reapproval(auth, form_source, db, change):
    data = preview(auth, form_source)
    item = prepare(auth, form_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    _, _, draft, profile, sender, fields = form_source
    if change == "sender":
        sender.email = "changed@example.com"
    elif change == "draft":
        draft.body = "新しい文面"
    elif change == "mapping":
        fields[0].label = "変更後の項目"
    else:
        profile.fingerprint = "b" * 64
    db.commit()
    result = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-approval-request",
        json={
            "expected_preparation_hash": data["preparation_hash"],
        },
    )
    assert result.status_code == 409
    revoked = auth.get(f"/api/approval-requests/{item['id']}").json()
    assert revoked["status"] == "REVOKED"
    assert revoked["invalidation_reason"]


@pytest.mark.parametrize(
    "block", ["contact", "captcha", "prohibited", "missing", "file", "duplicate"]
)
def test_ineligible_preparation_rejected(auth, form_source, db, block):
    _, company, _, profile, sender, fields = form_source
    if block == "contact":
        company.do_not_contact = True
    elif block == "captcha":
        profile.captcha_type = "CAPTCHA_RECAPTCHA"
    elif block == "prohibited":
        profile.sales_contact_status = "PROHIBITED"
    elif block == "missing":
        sender.email = ""
    elif block == "file":
        fields[0].field_type = "file"
    else:
        fields[0].name = fields[1].name
    db.commit()
    assert (
        auth.get(f"/api/outreach-drafts/{form_source[2].id}/form-approval-preview").status_code
        == 409
    )


def test_other_user_cannot_prepare(auth, form_source, users):
    from tests.conftest import PASSWORD

    auth.post("/api/auth/logout")
    assert (
        auth.post(
            "/api/auth/login", json={"email": users[1].email, "password": PASSWORD}
        ).status_code
        == 200
    )
    assert (
        auth.get(f"/api/outreach-drafts/{form_source[2].id}/form-approval-preview").status_code
        == 404
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{form_source[2].id}/form-approval-request",
            json={
                "expected_preparation_hash": "a" * 64,
            },
        ).status_code
        == 404
    )


def test_confirmed_cannot_replace_preparation_hash(auth, form_source):
    result = auth.post(
        f"/api/outreach-drafts/{form_source[2].id}/form-approval-request",
        json={
            "expected_preparation_hash": "a" * 64,
            "confirmed": True,
        },
    )
    assert result.status_code == 422


@pytest.mark.parametrize("mixed", [False, True])
def test_agent_cannot_use_human_preparation(auth, form_source, monkeypatch, mixed):
    from app.config import settings
    from tests.test_approval_foundation import agent_token

    monkeypatch.setattr(settings, "agent_features_enabled", True)
    issued = agent_token(auth, form_source[:2])
    if not mixed:
        auth.cookies.clear()
    headers = {"Authorization": f"Bearer {issued['token']}"}
    assert (
        auth.get(
            f"/api/outreach-drafts/{form_source[2].id}/form-approval-preview", headers=headers
        ).status_code
        == 403
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{form_source[2].id}/form-approval-request",
            headers=headers,
            json={"expected_preparation_hash": "a" * 64},
        ).status_code
        == 403
    )


def test_viewer_cannot_prepare(auth, form_source, users, db):
    from app.models import ProjectMember
    from tests.conftest import PASSWORD

    db.add(ProjectMember(project_id=form_source[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert (
        auth.get(f"/api/outreach-drafts/{form_source[2].id}/form-approval-preview").status_code
        == 404
    )
