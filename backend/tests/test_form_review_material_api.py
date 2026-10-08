import pytest
from sqlalchemy import text

from app.models import (
    Company,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    ProjectMember,
)


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
