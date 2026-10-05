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
        action_url=company.contact_url + "/submit",
        form_status="READY",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        confirmation_page=False,
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
            confidence=1.0,
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


def test_legacy_ready_profile_with_duplicate_body_cannot_prepare(auth, form_source, db):
    profile = form_source[3]
    db.add(
        FormProfileField(
            form_profile_id=profile.id,
            position=9,
            name="second_body",
            field_type="textarea",
            mapped_key="message",
            confidence=1.0,
        )
    )
    db.commit()
    response = auth.get(f"/api/outreach-drafts/{form_source[2].id}/form-approval-preview")
    assert response.status_code == 409
    assert "複数" in str(response.json())


@pytest.mark.parametrize(
    "value,source,status",
    [
        ("", "RULE", 409),
        ("invalid", "MANUAL", 409),
        ("mail", "OPENAI", 409),
        ("tel", "MANUAL", 409),
        ("mail", "MANUAL", 200),
    ],
)
def test_contact_method_preparation_requires_explicit_valid_choice(
    auth, form_source, db, value, source, status
):
    db.add(
        FormProfileField(
            form_profile_id=form_source[3].id,
            position=9,
            name="reply_method",
            label="連絡方法",
            field_type="radio",
            required=True,
            mapped_key="contact_method",
            confidence=0.9,
            decision_source=source,
            recommended_value=value,
            options=[{"value": "mail", "label": "メール"}, {"value": "tel", "label": "電話"}],
        )
    )
    db.commit()
    result = auth.get(f"/api/outreach-drafts/{form_source[2].id}/form-approval-preview")
    assert result.status_code == status
    if status == 200:
        assert result.json()["proposal"]["field_values"]["reply_method"] == "mail"


def test_human_contact_method_correction_can_prepare_without_sending(auth, form_source, db):
    profile = form_source[3]
    profile.form_status = "REVIEW_REQUIRED"
    field = FormProfileField(
        form_profile_id=profile.id,
        position=9,
        name="reply_method",
        label="連絡方法",
        field_type="radio",
        required=True,
        mapped_key="contact_method",
        confidence=0.9,
        decision_source="RULE",
        options=[{"value": "m", "label": "メール"}],
    )
    db.add(field)
    db.commit()
    response = auth.patch(
        f"/api/form-profile-fields/{field.id}",
        json={"mapped_key": "contact_method", "recommended_value": "m", "reason": "連絡方法を確認"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["decision_source"] == "MANUAL"
    assert preview(auth, form_source)["proposal"]["field_values"]["reply_method"] == "m"
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == 0


def test_changed_contact_method_revokes_existing_approval(auth, form_source, db):
    field = FormProfileField(
        form_profile_id=form_source[3].id,
        position=9,
        name="reply_method",
        label="連絡方法",
        field_type="radio",
        required=True,
        mapped_key="contact_method",
        confidence=1.0,
        decision_source="MANUAL",
        recommended_value="m",
        options=[{"value": "m", "label": "メール"}, {"value": "t", "label": "電話"}],
    )
    db.add(field)
    db.commit()
    item = prepare(auth, form_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    field.recommended_value = "t"
    db.commit()
    refreshed = auth.get(f"/api/approval-requests/{item['id']}").json()
    assert refreshed["status"] == "REVOKED"


def test_sender_contact_guard_stops_before_fetch(form_source, db, monkeypatch):
    from app.services.form_delivery import FormDeliveryError
    from app.services.form_profile_delivery import inspect_delivery_profile

    field = FormProfileField(
        form_profile_id=form_source[3].id,
        position=9,
        name="reply_method",
        label="連絡方法",
        field_type="radio",
        required=True,
        mapped_key="contact_method",
        confidence=1.0,
        decision_source="MANUAL",
        recommended_value="t",
        options=[{"value": "t", "label": "電話"}],
    )
    db.add(field)
    db.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("Missing sender phone must stop before website access")

    monkeypatch.setattr("app.services.form_profile_delivery.inspect_form", forbidden)
    with pytest.raises(FormDeliveryError, match="送信者"):
        inspect_delivery_profile(db, form_source[1], form_source[2])


@pytest.mark.parametrize(
    "key,required,source,value,status",
    [
        ("privacy_consent", True, "RULE", "yes", 409),
        ("privacy_consent", True, "MANUAL", "", 409),
        ("privacy_consent", True, "MANUAL", "wrong", 409),
        ("privacy_consent", True, "MANUAL", "yes", 200),
        ("newsletter_consent", False, "RULE", "yes", 409),
        ("newsletter_consent", False, "MANUAL", "", 200),
    ],
)
def test_consent_preparation_requires_human_choice(
    auth, form_source, db, key, required, source, value, status
):
    label = "プライバシーに同意" if key == "privacy_consent" else "メルマガ登録"
    db.add(
        FormProfileField(
            form_profile_id=form_source[3].id,
            position=9,
            name="consent_choice",
            label=label,
            field_type="checkbox",
            required=required,
            mapped_key=key,
            confidence=1.0,
            decision_source=source,
            recommended_value=value,
            options=[{"value": "yes", "label": label}],
        )
    )
    db.commit()
    result = auth.get(f"/api/outreach-drafts/{form_source[2].id}/form-approval-preview")
    assert result.status_code == status
    if status == 200:
        values = result.json()["proposal"]["field_values"]
        if value:
            assert values["consent_choice"] == value
        else:
            assert "consent_choice" not in values


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
