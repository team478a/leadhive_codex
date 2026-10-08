from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.models import (
    Company,
    FormAnalysisLog,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    ProjectMember,
)
from app.services.form_intelligence.fields import GROUP_REVIEW_MARKER, mapping_review_reason


def make_company(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "Review material test",
            "target_profile_id": profile_id,
            "sales_objective": "Partnership",
            "region": "Tokyo",
            "status": "active",
        },
    ).json()
    company = Company(
        project_id=project["id"],
        company_name="Fixture",
        domain="review.example",
        website_url="https://review.example",
        source="url",
    )
    db.add(company)
    db.commit()
    return project, company


def seed(auth, db):
    project, company = make_company(auth, db)
    profile = FormProfile(
        company_id=company.id,
        form_url=company.website_url + "/contact",
        form_found=True,
        form_status="REVIEW_REQUIRED",
        sales_contact_status="UNCERTAIN",
    )
    db.add(profile)
    db.flush()
    db.add_all(
        [
            FormProfileField(
                form_profile_id=profile.id,
                position=0,
                name="body",
                field_type="textarea",
                mapped_key="message",
                required=True,
            ),
            FormProfileField(
                form_profile_id=profile.id,
                position=1,
                name="email",
                field_type="email",
                mapped_key="email",
                required=True,
            ),
        ]
    )
    db.commit()
    return project, company, profile


def test_read_only_material_missing_draft_and_agent_rejected(auth, db):
    _, _, profile = seed(auth, db)
    db.add(
        FormProfileField(
            form_profile_id=profile.id,
            position=2,
            name="services[]",
            field_type="checkbox",
            label="事業内容",
            options=[{"label": "SNS運用", "value": "SNS"}, {"label": "OEM", "value": "OEM"}],
        )
    )
    db.commit()
    tables = (
        "form_profiles",
        "form_profile_fields",
        "outreach_drafts",
        "approval_requests",
        "email_deliveries",
        "form_deliveries",
        "operation_jobs",
        "form_analysis_logs",
    )
    before = {
        table: db.execute(text("SELECT row_to_json(t)::text FROM " + table + " t")).scalars().all()
        for table in tables
    }
    path = f"/api/form-profiles/{profile.id}/review-material"
    result = auth.get(path)
    assert result.status_code == 200
    body = result.json()
    assert body["draft_id"] is None and body["missing_required_values"] == 2
    assert not body["execution_supported"] and not body["human_approved"]
    assert not body["live_form_checked"]
    structure = body["saved_choice_structure"]
    assert len(structure["groups"]) == 1
    assert not structure["execution_allowed"] and not structure["eligible_for_approval"]
    assert structure["groups"][0]["options"][0]["value"] == "SNS"
    assert body["technical_diagnostic"]["route"] == "UNKNOWN"
    assert not body["technical_diagnostic"]["execution_allowed"]
    assert not body["technical_diagnostic"]["live_fetch_performed"]
    assert auth.get(
        path, headers={"Authorization": "Bearer invalid-agent-credential"}
    ).status_code in (401, 403)
    after = {
        table: db.execute(text("SELECT row_to_json(t)::text FROM " + table + " t")).scalars().all()
        for table in tables
    }
    assert before == after


def test_latest_form_draft_and_admin_sender_only(auth, db, users):
    _, company, profile = seed(auth, db)
    users[0].is_admin = True
    db.add(FormSenderSettings(id=1, email="sender@example.test"))
    draft = OutreachDraft(company_id=company.id, channel="form", body="Safe draft")
    db.add_all([draft, OutreachDraft(company_id=company.id, channel="email", body="Wrong channel")])
    db.commit()
    body = auth.get(f"/api/form-profiles/{profile.id}/review-material").json()
    assert body["draft_id"] == str(draft.id) and len(body["draft_hash"]) == 64
    assert body["sender_settings_visible"]
    assert [item["proposed_value"] for item in body["items"]] == [
        "Safe draft",
        "sender@example.test",
    ]
    assert body["permission_status"] != "ALLOWED"


def test_other_project_and_viewer_sender_privacy(auth, db, users):
    project, company, profile = seed(auth, db)
    db.add(FormSenderSettings(id=1, email="private@example.test"))
    db.add(OutreachDraft(company_id=company.id, channel="form", body="Project draft"))
    db.commit()
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    path = f"/api/form-profiles/{profile.id}/review-material"
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=project["id"], user_id=users[1].id, role="viewer"))
    db.commit()
    response = auth.get(path)
    assert response.status_code == 200
    assert not response.json()["sender_settings_visible"]
    assert "private@example.test" not in response.text
    assert response.json()["items"][0]["proposed_value"] == "Project draft"
    auth.cookies.clear()
    assert auth.get(path).status_code == 401


@pytest.mark.parametrize(
    "sales,expected", [("UNCERTAIN", "REVIEW_REQUIRED"), ("PROHIBITED", "BLOCKED")]
)
def test_human_choice_does_not_authorize_sending(auth, db, sales, expected):
    _, _, profile = seed(auth, db)
    profile.sales_contact_status = sales
    profile.delivery_supported = False
    consent = FormProfileField(
        form_profile_id=profile.id,
        position=2,
        name="consent",
        label="プライバシー同意",
        field_type="checkbox",
        mapped_key="privacy_consent",
        required=True,
        options=[{"value": "yes", "label": "同意"}],
    )
    db.add(consent)
    db.commit()
    tables = ("approval_requests", "human_approval_proofs", "email_deliveries", "form_deliveries")
    before = {
        table: db.execute(text("SELECT count(*) FROM " + table)).scalar_one() for table in tables
    }
    payload = {
        "mapped_key": "privacy_consent",
        "recommended_value": "yes",
        "reason": "Human reviewed",
    }
    path = f"/api/form-profile-fields/{consent.id}"
    assert auth.patch(
        path, json=payload, headers={"Authorization": "Bearer agent-not-human"}
    ).status_code in (401, 403)
    result = auth.patch(path, json=payload)
    assert result.status_code == 200 and result.json()["decision_source"] == "MANUAL"
    db.refresh(profile)
    assert profile.form_status == expected and not profile.delivery_supported
    assert before == {
        table: db.execute(text("SELECT count(*) FROM " + table)).scalar_one() for table in tables
    }


def seed_group(auth, db):
    project, company, profile = seed(auth, db)
    profile.fingerprint = "a" * 64
    fields = [
        FormProfileField(
            form_profile_id=profile.id,
            position=pos,
            name=name,
            label="お問い合わせ項目 必須" + GROUP_REVIEW_MARKER,
            field_type="checkbox",
            mapped_key="other",
            required=False,
            options=[{"value": value, "label": value}],
        )
        for pos, name, value in [(2, "web[]", "WEB"), (3, "other[]", "OTHER")]
    ]
    db.add_all(fields)
    db.commit()
    path = f"/api/form-profiles/{profile.id}/choice-groups"
    group = auth.get(path).json()[0]
    payload = {
        "expected_source_hash": group["source_hash"],
        "rule": "AT_LEAST_ONE",
        "selections": [{"field_id": str(fields[1].id), "value": "OTHER"}],
        "membership_and_rule_confirmed": True,
    }
    return project, company, profile, fields, path, group, payload


@pytest.mark.parametrize(
    "sales,expected", [("UNCERTAIN", "REVIEW_REQUIRED"), ("PROHIBITED", "BLOCKED")]
)
def test_group_record_is_atomic_human_review_not_dispatch(auth, db, users, sales, expected):
    _, _, profile, fields, path, group, payload = seed_group(auth, db)
    profile.sales_contact_status = sales
    db.commit()
    response = auth.post(path + f"/{group['group_id']}/review", json=payload)
    assert response.status_code == 200
    assert response.json()[0]["review_status"] == "RECORDED"
    assert response.json()[0]["execution_supported"] is False
    db.refresh(profile)
    assert profile.form_status == expected
    for f in fields:
        db.refresh(f)
    assert [f.recommended_value for f in fields] == ["", "OTHER"]
    assert all(f.decision_source == "MANUAL" and GROUP_REVIEW_MARKER in f.label for f in fields)
    assert "グループ" in mapping_review_reason(
        [{"field_type": f.field_type, "label": f.label} for f in fields]
    )
    log = db.scalar(
        select(FormAnalysisLog).where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == "choice_group_review",
        )
    )
    assert log.actor_user_id == users[0].id and not log.details["send_authorized"]
    assert all(
        db.execute(text("SELECT count(*) FROM " + table)).scalar_one() == 0
        for table in (
            "approval_requests",
            "human_approval_proofs",
            "email_deliveries",
            "form_deliveries",
        )
    )


@pytest.mark.parametrize(
    "change", ["empty", "duplicate", "bad_value", "outside", "exactly_two", "unconfirmed", "extra"]
)
def test_group_invalid_choice_never_partially_changes_fields(auth, db, change):
    _, _, profile, fields, path, group, payload = seed_group(auth, db)
    if change == "empty":
        payload["selections"] = []
    elif change == "duplicate":
        payload["selections"] *= 2
    elif change == "bad_value":
        payload["selections"][0]["value"] = "UNKNOWN"
    elif change == "outside":
        payload["selections"][0]["field_id"] = str(profile.id)
    elif change == "exactly_two":
        payload["rule"] = "EXACTLY_ONE"
        payload["selections"].append({"field_id": str(fields[0].id), "value": "WEB"})
    elif change == "unconfirmed":
        payload["membership_and_rule_confirmed"] = False
    else:
        payload["confirmed"] = True
    assert auth.post(path + f"/{group['group_id']}/review", json=payload).status_code == 422
    for f in fields:
        db.refresh(f)
        assert f.recommended_value == "" and f.decision_source != "MANUAL"
    assert (
        db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.form_profile_id == profile.id))
        is None
    )


def test_group_stale_input_and_individual_required(auth, db):
    _, _, _, fields, path, group, payload = seed_group(auth, db)
    fields[0].required = True
    db.commit()
    assert auth.post(path + f"/{group['group_id']}/review", json=payload).status_code == 409
    payload["expected_source_hash"] = auth.get(path).json()[0]["source_hash"]
    assert auth.post(path + f"/{group['group_id']}/review", json=payload).status_code == 422


def test_group_viewer_other_project_and_agent_denied(auth, db, users):
    project, _, _, _, path, group, payload = seed_group(auth, db)
    write = path + f"/{group['group_id']}/review"
    assert auth.post(
        write, json=payload, headers={"Authorization": "Bearer not-human"}
    ).status_code in (401, 403)
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=project["id"], user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(path).status_code == 200
    assert auth.post(write, json=payload).status_code == 404


def test_group_expiration_and_changes_invalidate_ledger(auth, db):
    _, _, profile, fields, path, group, payload = seed_group(auth, db)
    assert auth.post(path + f"/{group['group_id']}/review", json=payload).status_code == 200
    log = db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.form_profile_id == profile.id))
    log.details = log.details | {
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    }
    db.commit()
    assert auth.get(path).json()[0]["review_status"] == "EXPIRED"
    fields[1].recommended_value = ""
    db.commit()
    assert auth.get(path).json()[0]["review_status"] == "STALE"


@pytest.mark.parametrize("status", ["STALE", "ERROR"])
def test_group_review_cannot_clear_live_check_failure(auth, db, status):
    _, _, profile, _, path, group, payload = seed_group(auth, db)
    write = path + f"/{group['group_id']}/review"
    assert auth.post(write, json=payload).status_code == 200
    profile.form_status = status
    profile.delivery_supported = False
    profile.review_reason = "最新状態を確認できません"
    db.commit()
    payload["expected_source_hash"] = auth.get(path).json()[0]["source_hash"]
    assert auth.get(path).json()[0]["review_status"] == "STALE"
    assert auth.post(write, json=payload).status_code == 409
    db.refresh(profile)
    assert profile.form_status == status and profile.review_reason == "最新状態を確認できません"


@pytest.mark.parametrize("bad", ["unnamed", "consent", "duplicates", "duplicate_option_values"])
def test_group_unsupported_shapes_are_not_reviewable(auth, db, bad):
    _, _, _, fields, path, group, payload = seed_group(auth, db)
    if bad == "unnamed":
        fields[0].name = ""
    elif bad == "consent":
        fields[0].mapped_key = "privacy_consent"
    elif bad == "duplicates":
        fields[0].name = fields[1].name
    else:
        fields[0].options = [{"value": "a"}, {"value": "a"}]
    db.commit()
    current = auth.get(path).json()[0]
    assert not current["review_supported"]
    payload["expected_source_hash"] = current["source_hash"]
    assert auth.post(path + f"/{group['group_id']}/review", json=payload).status_code == 422


def test_group_multiple_checkbox_options_allow_one_value_per_field(auth, db):
    _, _, _, fields, path, group, payload = seed_group(auth, db)
    fields[0].options = [{"value": "a", "label": "Option A"}, {"value": "b", "label": "Option B"}]
    db.commit()
    current = auth.get(path).json()[0]
    assert current["review_supported"]
    payload["expected_source_hash"] = current["source_hash"]
    payload["selections"] = [{"field_id": str(fields[0].id), "value": "b"}]
    result = auth.post(path + f"/{group['group_id']}/review", json=payload)
    assert result.status_code == 200 and result.json()[0]["review_status"] == "RECORDED"
    db.refresh(fields[0])
    assert fields[0].recommended_value == "b"
