"""Human purpose attestation security, expiry and compatibility, synthetic only."""

import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalRequest,
    Company,
    DestinationReviewEvent,
    EmailDelivery,
    FormDelivery,
    FormProfileField,
    LeadSiteEvidence,
    Project,
    ProjectMember,
)
from app.services.destination_review import state
from app.services.lead_identity import identity_hash
from tests.test_sendability import codes, company_fixture, profile_fixture


def reviewed_fixture(auth, db):
    company = company_fixture(auth, db)
    profile = profile_fixture(db, company)
    db.add(
        LeadSiteEvidence(
            company_id=company.id,
            source_url=company.website_url,
            identity_hash=identity_hash(company),
            confidence="CONFIRMED",
            reasons=["NAME_MATCH", "ADDRESS_MATCH"],
        )
    )
    db.commit()
    auth.post(f"/api/projects/{company.project_id}/lead-destinations/refresh", json={})
    path = f"/api/companies/{company.id}/sendability"
    item = auth.get(path).json()["destinations"][0]
    review_path = f"/api/companies/{company.id}/destinations/{item['id']}/reviews"
    payload = dict(
        expected_hash=item["expected_hash"],
        expected_review_version=0,
        purpose="business",
        scope="location",
        source_url="https://shop.example/contact",
        evidence_excerpt="事業提携などのお問い合わせはこちらです。",
    )
    return company, profile, path, review_path, payload


def test_human_review_ready_replay_stale_revision_and_revoke(auth, db):
    company, _, path, review_path, body = reviewed_fixture(auth, db)
    assert auth.post(review_path, json=body).status_code == 201
    result = auth.get(path).json()
    assert result["status"] == "READY" and result["destinations"][0]["review"]["state"] == "CURRENT"
    assert not result["dm_ready"] and not result["execution_allowed"]
    assert auth.post(review_path, json=body).status_code == 409
    company.address = "Changed 9-9"
    db.commit()
    result = auth.get(path).json()
    assert result["status"] == "REVIEW" and "DESTINATION_REVIEW_STALE" in codes(result)
    item = result["destinations"][0]
    body.update(expected_hash=item["expected_hash"], expected_review_version=1)
    assert auth.post(review_path, json=body).status_code == 201
    assert "IDENTITY_UNCERTAIN" in codes(auth.get(path).json())
    assert (
        auth.post(review_path + "/revoke", json={"expected_review_version": 1}).status_code == 409
    )
    assert (
        auth.post(review_path + "/revoke", json={"expected_review_version": 2}).status_code == 201
    )
    assert (
        auth.post(review_path + "/revoke", json={"expected_review_version": 3}).status_code == 409
    )
    assert "DESTINATION_REVIEW_REVOKED" in codes(auth.get(path).json())
    assert db.scalar(select(func.count()).select_from(DestinationReviewEvent)) == 3
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "change", ["field", "profile", "purpose", "scope", "prohibition", "shared"]
)
def test_review_cannot_override_safety_or_bind_changed_analysis(auth, db, change):
    company, profile, path, review_path, body = reviewed_fixture(auth, db)
    if change == "purpose":
        body["purpose"] = "reservation"
    if change == "scope":
        body["scope"] = "group"
    assert auth.post(review_path, json=body).status_code == 201
    if change == "field":
        field = db.scalar(
            select(FormProfileField).where(FormProfileField.form_profile_id == profile.id)
        )
        field.confidence = 0.2
    elif change == "profile":
        profile.fingerprint = "c" * 64
    elif change == "prohibition":
        company.do_not_contact = True
    elif change == "shared":
        from tests.test_location_import import import_locations

        import_locations(
            auth,
            {"id": str(company.project_id)},
            [["Second shop", "https://shop.example", "", "", "City 2-2", ""]],
        )
        other = db.scalar(select(Company).where(Company.id != company.id))
        other.contact_url = profile.form_url
    db.commit()
    result = auth.get(path).json()
    assert result["status"] != "READY"
    assert not result["execution_allowed"]
    if change in {"field", "profile"}:
        assert "DESTINATION_REVIEW_STALE" in codes(result)
    if change == "prohibition":
        assert result["status"] == "BLOCKED"
    if change == "shared":
        assert "SHARED_DESTINATION" in codes(result)


def test_expiry_public_evidence_validation_extra_input_and_conflict(auth, db):
    _, _, path, review_path, body = reviewed_fixture(auth, db)
    for source in [
        "https://other.example/contact",
        "http://localhost/contact",
        "https://shop.example/contact?token=secret",
        "https://user:secret@shop.example/contact",
    ]:
        assert auth.post(review_path, json={**body, "source_url": source}).status_code == 422
    assert auth.post(review_path, json={**body, "confirmed": True}).status_code == 422
    assert auth.post(review_path, json={**body, "expected_hash": "f" * 64}).status_code == 409
    assert auth.post(review_path, json={**body, "expires_at": "2099-01-01"}).status_code == 422
    assert auth.post(review_path, json=body).status_code == 201
    row = db.scalar(select(DestinationReviewEvent))
    assert row.expires_at - row.created_at == timedelta(days=7)
    assert state(row, row.snapshot_hash, row.expires_at) == "EXPIRED"
    assert state(row, "changed", row.created_at) == "STALE"
    assert auth.get(path).json()["destinations"][0]["review"]["version"] == 1


def test_viewer_other_project_agent_and_append_only_db_boundary(auth, db, users):
    company, _, path, review_path, body = reviewed_fixture(auth, db)
    assert (
        auth.post(
            review_path, json=body, headers={"Authorization": "Bearer invalid-agent"}
        ).status_code
        == 403
    )
    assert auth.post(review_path, json=body).status_code == 201
    row = db.scalar(select(DestinationReviewEvent))
    for statement in [
        update(DestinationReviewEvent).values(purpose="sales"),
        delete(DestinationReviewEvent),
        text("TRUNCATE destination_review_events"),
    ]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(statement)
    project = db.get(Project, company.project_id)
    project.user_id = users[1].id
    db.commit()
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(path).json()["can_review"] is False
    assert auth.post(review_path, json={**body, "expected_review_version": 1}).status_code == 404
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            DestinationReviewEvent(
                project_id=project.id,
                company_id=company.id,
                destination_id=row.destination_id,
                actor_user_id=users[0].id,
                version=2,
                event_type="REVOKED",
                purpose=row.purpose,
                scope=row.scope,
                source_url=row.source_url,
                evidence_excerpt=row.evidence_excerpt,
                snapshot_hash=row.snapshot_hash,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        db.flush()


def test_evidence_survives_company_delete_and_downgrade_refused(auth, db):
    company, _, _, review_path, body = reviewed_fixture(auth, db)
    assert auth.post(review_path, json=body).status_code == 201
    module = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "migrations/versions/e49867e60dcd_human_destination_purpose_review_.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="evidence exists"):
            module["downgrade"]()
    db.delete(company)
    db.commit()
    assert db.scalar(select(func.count()).select_from(DestinationReviewEvent)) == 1
    # Existing owner Project deletion still cascades, without a ledger-only bypass API.
    db.delete(db.get(Project, company.project_id))
    db.commit()
    assert db.scalar(select(func.count()).select_from(DestinationReviewEvent)) == 0
