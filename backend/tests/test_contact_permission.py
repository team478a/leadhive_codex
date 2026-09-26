from app.models import Company, FormProfile, SuppressionEntry
from app.services.contact_permission import evaluate_contact_permission


def make_company(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "連絡可否判定",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "全国",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://permission.example"]},
    )
    company_data = auth.get(f"/api/projects/{project['id']}/companies").json()[0]
    company = db.get(Company, company_data["id"])
    company.email = "contact@permission.example"
    company.contact_url = "https://permission.example/contact"
    db.commit()
    return project, company


def test_contact_permission_combines_company_suppression_quality_and_form_profile(auth, db):
    project, company = make_company(auth, db)

    email = evaluate_contact_permission(db, company.project_id, company.id, "email", company.email)
    assert (email.status, email.reason_code) == ("ALLOWED", "allowed")

    company.contact_quality_status = "invalid"
    db.commit()
    invalid = evaluate_contact_permission(
        db, company.project_id, company.id, "email", company.email
    )
    assert (invalid.status, invalid.reason_code) == (
        "PROHIBITED",
        "contact_quality_invalid",
    )

    company.contact_quality_status = "verified"
    suppression = SuppressionEntry(
        project_id=company.project_id,
        email=company.email.upper(),
        reason="配信停止",
    )
    db.add(suppression)
    db.commit()
    suppressed = evaluate_contact_permission(
        db, company.project_id, company.id, "email", company.email
    )
    assert (suppressed.status, suppressed.reason_code) == (
        "PROHIBITED",
        "suppression_email",
    )
    db.delete(suppression)
    db.commit()

    unanalyzed = evaluate_contact_permission(
        db, company.project_id, company.id, "form", company.contact_url
    )
    assert (unanalyzed.status, unanalyzed.reason_code) == (
        "UNCERTAIN",
        "form_unanalyzed",
    )

    form_profile = FormProfile(
        company_id=company.id,
        form_url=company.contact_url,
        form_index=0,
        form_status="READY",
        sales_contact_status="UNCERTAIN",
        captcha_type="CAPTCHA_NONE",
        delivery_supported=True,
        is_primary=True,
        form_found=True,
    )
    db.add(form_profile)
    db.commit()
    uncertain = evaluate_contact_permission(
        db, company.project_id, company.id, "form", company.contact_url
    )
    assert (uncertain.status, uncertain.reason_code) == (
        "UNCERTAIN",
        "form_sales_uncertain",
    )

    form_profile.sales_contact_status = "ALLOWED"
    db.commit()
    allowed = evaluate_contact_permission(
        db, company.project_id, company.id, "form", company.contact_url
    )
    assert (allowed.status, allowed.reason_code) == ("ALLOWED", "allowed")

    form_profile.sales_contact_status = "PROHIBITED"
    db.commit()
    prohibited = evaluate_contact_permission(
        db, company.project_id, company.id, "form", company.contact_url
    )
    assert (prohibited.status, prohibited.reason_code) == (
        "PROHIBITED",
        "form_sales_prohibited",
    )

    other_project = auth.post(
        "/api/projects",
        json={
            "project_name": "別プロジェクト",
            "target_profile_id": project["target_profile_id"],
            "sales_objective": "別案件",
            "region": "全国",
            "status": "active",
        },
    ).json()
    inaccessible = evaluate_contact_permission(
        db, other_project["id"], company.id, "email", company.email
    )
    assert (inaccessible.status, inaccessible.reason_code) == (
        "PROHIBITED",
        "company_not_accessible",
    )
