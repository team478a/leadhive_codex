import json

import pytest
from sqlalchemy import func, select

from app.models import Activity, ApprovalRequest, EmailDelivery, FormDelivery, ProjectMember
from app.services.collection_feedback import PREFIX
from app.services.scraper import PageData
from app.services.web_analysis import update_unprotected_fields
from tests.test_sendability import company_fixture


def body(company, **changes):
    return {
        "subject": "contact_url",
        "outcome": "OK",
        "reason": "confirmed",
        "expected_updated_at": company.updated_at.isoformat(),
        **changes,
    }


def test_feedback_corrects_protects_and_records_without_approval(auth, db):
    company = company_fixture(auth, db)
    company.contact_url = "https://shop.example/post/notice"
    db.commit()
    old = body(
        company, outcome="CORRECTED", reason="article", corrected_url="https://shop.example/contact"
    )
    path = f"/api/companies/{company.id}/collection-feedback"
    response = auth.post(path, json=old)
    assert response.status_code == 201
    assert response.json()["execution_allowed"] is False
    db.refresh(company)
    assert company.contact_url == "https://shop.example/contact"
    assert "contact_url" in company.protected_fields
    update_unprotected_fields(company, PageData(contact_url="https://shop.example/wrong"))
    assert company.contact_url == "https://shop.example/contact"
    assert auth.post(path, json=old).status_code == 409
    rows = auth.get(path).json()["items"]
    assert len(rows) == 1 and rows[0]["current"]
    assert rows[0]["before_contact_url"].endswith("/post/notice")
    assert rows[0]["actor_user_id"]
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_ng_clears_and_protects_destination_but_not_permission(auth, db):
    company = company_fixture(auth, db)
    company.contact_url = "https://shop.example/recruitment"
    company.do_not_contact = True
    db.commit()
    path = f"/api/companies/{company.id}/collection-feedback"
    assert (
        auth.post(path, json=body(company, outcome="NG", reason="recruitment")).status_code == 201
    )
    db.refresh(company)
    assert company.contact_url == "" and company.do_not_contact
    update_unprotected_fields(company, PageData(contact_url="https://shop.example/recruitment"))
    assert company.contact_url == ""
    assert auth.post(path, json=body(company)).status_code == 422


def test_company_ng_is_excluded_and_ok_does_not_restore_it(auth, db):
    company = company_fixture(auth, db)
    path = f"/api/companies/{company.id}/collection-feedback"
    assert (
        auth.post(
            path, json=body(company, subject="company", outcome="NG", reason="wrong_industry")
        ).status_code
        == 201
    )
    db.refresh(company)
    assert company.status == "excluded"
    assert auth.post(path, json=body(company, subject="company")).status_code == 201
    db.refresh(company)
    assert company.status == "excluded"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://127.0.0.1/contact",
        "https://localhost/contact",
        "https://user:password@example.com/contact",
        "https://example.com:8000/contact",
    ],
)
def test_unsafe_corrections_rejected(auth, db, url):
    company = company_fixture(auth, db)
    path = f"/api/companies/{company.id}/collection-feedback"
    assert (
        auth.post(
            path, json=body(company, outcome="CORRECTED", reason="other", corrected_url=url)
        ).status_code
        == 422
    )
    assert not db.scalar(select(Activity.id).where(Activity.note.startswith(PREFIX)))


def test_viewer_cross_project_agent_and_reserved_note(auth, db, users):
    company = company_fixture(auth, db)
    path = f"/api/companies/{company.id}/collection-feedback"
    payload = body(company, subject="company")
    assert (
        auth.post(path, headers={"Authorization": "Bearer fake-agent"}, json=payload).status_code
        == 403
    )
    assert (
        auth.post(
            f"/api/companies/{company.id}/activities",
            json={"activity_type": "note", "note": PREFIX + json.dumps({"outcome": "OK"})},
        ).status_code
        == 422
    )
    auth.post("/api/auth/logout")
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.post(path, json=payload).status_code == 404
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(path).status_code == 200
    assert auth.post(path, json=payload).status_code == 404
