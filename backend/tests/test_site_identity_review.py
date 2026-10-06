"""Synthetic Human identity attestation and READY-only recommendation safeguards."""

import runpy
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalRequest,
    Company,
    EmailDelivery,
    FormDelivery,
    Project,
    ProjectMember,
    SiteIdentityReviewEvent,
)
from app.services.destination_selection import recommend
from app.services.lead_identity import identity_hash
from app.services.location_identity import location_key
from app.services.site_identity_review import confirmation, state
from tests.test_sendability import codes, company_fixture, profile_fixture


def fixture(auth, db):
    company = company_fixture(auth, db)
    profile_fixture(db, company)
    path = f"/api/companies/{company.id}/site-identity-reviews"
    body = dict(
        expected_hash=identity_hash(company),
        expected_review_version=0,
        source_url="https://shop.example/about",
        observed_name=company.company_name,
        observed_address=company.address,
        observed_phone="",
        evidence_excerpt="公式店舗案内で名称と番地を含む住所を確認しました。",
    )
    return company, path, body


def test_identity_current_revoke_expire_stale_and_no_send(auth, db):
    company, path, body = fixture(auth, db)
    assert "IDENTITY_UNCERTAIN" in codes(
        auth.get(f"/api/companies/{company.id}/sendability").json()
    )
    assert auth.post(path, json=body).status_code == 201
    assert confirmation(db, company) == "HUMAN_OBSERVED"
    row = db.scalar(select(SiteIdentityReviewEvent))
    assert row.expires_at - row.created_at == timedelta(days=7)
    assert state(row, row.identity_hash, row.expires_at) == "EXPIRED"
    assert confirmation(db, company, row.expires_at) is None
    assert auth.post(path, json=body).status_code == 409
    result = auth.get(f"/api/companies/{company.id}/lead-completion").json()
    assert (
        result["identity_status"] == "CONFIRMED"
        and result["identity_confirmation_source"] == "HUMAN_OBSERVED"
    )
    company.phone = "0791234567"
    db.commit()
    assert confirmation(db, company) is None
    assert (
        auth.get(f"/api/companies/{company.id}/lead-completion").json()["human_identity_review"][
            "state"
        ]
        == "STALE"
    )
    assert auth.post(path, json=body).status_code == 409
    body.update(expected_hash=identity_hash(company), expected_review_version=1)
    assert auth.post(path, json=body).status_code == 201
    assert auth.post(path + "/revoke", json={"expected_review_version": 1}).status_code == 409
    assert auth.post(path + "/revoke", json={"expected_review_version": 2}).status_code == 201
    assert confirmation(db, company) is None
    assert auth.post(path + "/revoke", json={"expected_review_version": 3}).status_code == 409
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_preview_is_read_only_and_uses_confirmation_rules(auth, db):
    company, path, body = fixture(auth, db)
    response = auth.post(path + "/preview", json=body)
    assert response.status_code == 200
    assert response.json() == {
        "comparison": "CONFIRMED",
        "reasons": ["COMPANY_NAME_MATCH", "ADDRESS_MATCH", "DOMAIN_MATCH"],
        "can_record": True,
        "review_recorded": False,
        "execution_allowed": False,
        "live_site_checked": False,
    }
    assert confirmation(db, company) is None
    for model in (SiteIdentityReviewEvent, ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    conflict = {**body, "observed_address": "Other city 9-9"}
    result = auth.post(path + "/preview", json=conflict).json()
    assert not result["can_record"] and result["reasons"] == ["ADDRESS_CONFLICT"]
    assert auth.post(path, json=conflict).status_code == 422
    name_only = {**body, "observed_address": ""}
    assert not auth.post(path + "/preview", json=name_only).json()["can_record"]
    assert auth.post(path, json=name_only).status_code == 422
    assert auth.post(path + "/preview", json={**body, "confirmed": True}).status_code == 422
    assert (
        auth.post(path + "/preview", json={**body, "source_url": "http://localhost/"}).status_code
        == 422
    )
    inventory = auth.get(f"/api/companies/{company.id}/lead-completion").json()
    assert inventory["identity_target"]["company_name"] == company.company_name
    assert inventory["identity_target"]["address"] == company.address
    assert auth.post(path, json=body).status_code == 201
    assert auth.post(path + "/preview", json=body).status_code == 409


def test_preview_human_project_boundary_and_stale_target(auth, db, users):
    company, path, body = fixture(auth, db)
    assert (
        auth.post(
            path + "/preview", json=body, headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 403
    )
    company.phone = "0791234567"
    db.commit()
    assert auth.post(path + "/preview", json=body).status_code == 409
    body["expected_hash"] = identity_hash(company)
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    from tests.conftest import PASSWORD

    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert auth.get(f"/api/companies/{company.id}/lead-completion").status_code == 200
    assert auth.post(path + "/preview", json=body).status_code == 404
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == company.project_id))
    db.commit()
    assert auth.post(path + "/preview", json=body).status_code == 404
    assert db.scalar(select(func.count()).select_from(SiteIdentityReviewEvent)) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_address": ""},
        {"observed_name": "Other shop"},
        {"observed_address": "City"},
        {"observed_address": "City 9-9"},
        {"source_url": "https://other.example/about"},
        {"source_url": "https://shop.example/about?token=secret"},
        {"source_url": "http://localhost/about"},
        {"source_url": "https://user:secret@shop.example/about"},
        {"observed_phone": "short"},
        {"confirmed": True},
        {"expires_at": "2099-01-01"},
    ],
)
def test_insufficient_conflicting_evidence_and_approval_shortcuts_rejected(auth, db, changes):
    _, path, body = fixture(auth, db)
    assert auth.post(path, json={**body, **changes}).status_code == 422
    assert db.scalar(select(func.count()).select_from(SiteIdentityReviewEvent)) == 0


def test_phone_match_editor_boundary_and_immutable_ledger(auth, db, users):
    company, path, body = fixture(auth, db)
    company.phone = "0791234567"
    db.commit()
    body.update(
        expected_hash=identity_hash(company), observed_address="", observed_phone="079-123-4567"
    )
    assert (
        auth.post(path, json=body, headers={"Authorization": "Bearer invalid"}).status_code == 403
    )
    project = db.get(Project, company.project_id)
    db.add(ProjectMember(project_id=project.id, user_id=users[1].id, role="viewer"))
    project.user_id = users[1].id
    db.commit()
    assert auth.post(path, json=body).status_code == 404
    member = ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer")
    db.add(member)
    db.commit()
    assert auth.post(path, json=body).status_code == 404
    member.role = "editor"
    db.commit()
    assert auth.post(path, json=body).status_code == 201
    row = db.scalar(select(SiteIdentityReviewEvent))
    assert "PHONE_MATCH" in row.reasons
    for statement in [
        update(SiteIdentityReviewEvent).values(observed_name="Changed"),
        delete(SiteIdentityReviewEvent),
        text("TRUNCATE site_identity_review_events"),
    ]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(statement)
    # Never transfer identity evidence when the original Company disappears.
    db.delete(company)
    db.commit()
    assert db.scalar(select(func.count()).select_from(SiteIdentityReviewEvent)) == 1
    source = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "migrations/versions/15fcce21f276_human_official_site_identity_evidence.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="evidence exists"):
            source["downgrade"]()
    db.delete(project)
    db.commit()
    assert db.scalar(select(func.count()).select_from(SiteIdentityReviewEvent)) == 0


def test_identity_then_purpose_can_recommend_but_safety_still_dominates(auth, db):
    company, path, body = fixture(auth, db)
    auth.post(f"/api/projects/{company.project_id}/lead-destinations/refresh", json={})
    assessment = f"/api/companies/{company.id}/sendability"
    item = auth.get(assessment).json()["destinations"][0]
    purpose_path = f"/api/companies/{company.id}/destinations/{item['id']}/reviews"
    purpose = dict(
        expected_hash=item["expected_hash"],
        expected_review_version=0,
        purpose="business",
        scope="location",
        source_url="https://shop.example/contact",
        evidence_excerpt="事業提携についての窓口案内を確認しました。",
    )
    assert auth.post(purpose_path, json=purpose).status_code == 201
    assert auth.post(path, json=body).status_code == 201
    item = auth.get(assessment).json()["destinations"][0]
    assert item["review"]["state"] == "STALE"  # Identity evidence changed after purpose review.
    purpose.update(expected_hash=item["expected_hash"], expected_review_version=1)
    assert auth.post(purpose_path, json=purpose).status_code == 201
    result = auth.get(assessment).json()
    assert result["status"] == "READY" and result["recommended_destination"]["id"] == item["id"]
    assert not result["dm_ready"] and not result["execution_allowed"]
    company.do_not_contact = True
    db.commit()
    result = auth.get(assessment).json()
    assert result["status"] == "BLOCKED" and result["recommended_destination"] is None


def test_cohort_identity_diagnostics_use_same_current_evidence(auth, db):
    company, path, body = fixture(auth, db)
    cohort = auth.post(
        f"/api/projects/{company.project_id}/completion-cohorts",
        json={"name": "Identity synthetic"},
    ).json()
    url = f"/api/completion-cohorts/{cohort['id']}"
    assert auth.get(url).json()["diagnostics"]["official_evidence"] == 0
    auth.post(path, json=body)
    result = auth.get(url).json()
    assert result["diagnostics"]["official_evidence"] == 1
    assert result["dm_ready_rate"] is None
    auth.post(path + "/revoke", json={"expected_review_version": 1})
    assert auth.get(url).json()["diagnostics"]["official_evidence"] == 0


def test_recommendation_never_promotes_nonready_and_has_no_email_bias():
    rows = [
        dict(
            id="form",
            type="form",
            destination="form",
            status="READY",
            purpose="business",
            expected_hash="a",
        ),
        dict(
            id="email",
            type="email",
            destination="email",
            status="READY",
            purpose="general",
            expected_hash="b",
        ),
    ]
    assert recommend(rows)["recommended_destination"]["id"] == "form"
    rows[1]["purpose"] = "business"
    assert (
        recommend(rows)["recommended_destination"] is None
        and recommend(rows)["destination_selection_required"]
    )
    rows[1].update(status="BLOCKED", purpose="sales")
    assert recommend(rows)["recommended_destination"]["id"] == "form"
    rows[0]["status"] = "HOLD"
    assert recommend(rows)["recommended_destination"] is None


def test_company_location_and_same_domain_never_share_human_attestation(auth, db):
    company, path, body = fixture(auth, db)
    assert auth.post(path, json=body).status_code == 201
    other = Company(
        project_id=company.project_id,
        source="url",
        company_name="Other shop",
        website_url=company.website_url,
        domain=company.domain,
        address="City 2-2",
        record_type="location",
        location_key=location_key("Other shop", "City 2-2", company.website_url),
    )
    db.add(other)
    db.commit()
    assert confirmation(db, other) is None
    company.record_type = "company"
    company.location_key = ""
    db.commit()
    assert confirmation(db, company) is None


def test_human_revocation_does_not_rewrite_existing_automatic_evidence(auth, db):
    from app.models import LeadSiteEvidence

    company, path, body = fixture(auth, db)
    assert auth.post(path, json=body).status_code == 201
    db.add(
        LeadSiteEvidence(
            company_id=company.id,
            source_url=company.website_url,
            identity_hash=identity_hash(company),
            confidence="CONFIRMED",
            reasons=["NAME_MATCH", "PHONE_MATCH"],
        )
    )
    db.commit()
    auth.post(path + "/revoke", json={"expected_review_version": 1})
    assert confirmation(db, company) == "AUTOMATIC_RULE"
    assert db.scalar(select(func.count()).select_from(LeadSiteEvidence)) == 1
