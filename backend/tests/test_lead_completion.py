"""Lead inventory/provenance tests, synthetic only. No provider calls or dispatch."""

import runpy
from pathlib import Path
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Company,
    ContactDestination,
    LeadDestinationLink,
    LeadSiteEvidence,
    LeadSourceObservation,
    ProjectMember,
)
from app.services import collection_jobs
from app.services.collection import Candidate
from app.services.lead_identity import compare, identity_hash, site_queries
from tests.test_location_import import import_locations, make_project


def test_duplicate_becomes_enrichment_without_overwriting_confirmed_values(auth, db):
    project = make_project(auth)
    first = ["Salon ABC", "https://abc.example", "", "known@abc.example", "姫路市北町12-3", ""]
    assert import_locations(auth, project, [first]).json()["saved_count"] == 1
    second = ["Salon ABC", "https://abc.example", "0791234567", "wrong@other.example", first[4], ""]
    result = import_locations(auth, project, [second]).json()
    assert result["saved_count"] == 0 and result["duplicate_count"] == 1
    row = db.scalar(select(Company))
    assert row.email == "known@abc.example" and row.phone == "0791234567"
    events = db.scalars(
        select(LeadSourceObservation).order_by(LeadSourceObservation.observed_at)
    ).all()
    assert len(events) == 2
    assert events[-1].identity_status == "CONFIRMED"
    assert events[-1].applied_fields == ["phone"]
    assert events[-1].facts["email"]["value"] == "wrong@other.example"
    assert not events[-1].facts["email"]["verified"]


@pytest.mark.parametrize("protected", [False, True])
def test_ambiguous_or_protected_candidate_never_overwrites(auth, db, protected):
    project = make_project(auth)
    import_locations(auth, project, [["Salon ABC", "https://abc.example", "", "", "姫路市", ""]])
    row = db.scalar(select(Company))
    if protected:
        row.protected_fields = ["phone"]
        row.address = "姫路市北町12-3"
        from app.services.location_identity import location_key

        row.location_key = location_key(row.company_name, row.address, row.website_url)
        db.commit()
    import_locations(
        auth, project, [[row.company_name, row.website_url, "0791234567", "", row.address, ""]]
    )
    assert db.get(Company, row.id).phone == ""


def test_shared_domain_company_candidate_is_preserved_for_review(auth, db):
    project = make_project(auth)
    job = collection_jobs.start_job(db, UUID(project["id"]), "csv", "", "")
    collection_jobs.save_candidates(
        db, job, [Candidate("Alpha", "https://group.example", "Tokyo 1-1")]
    )
    job = collection_jobs.start_job(db, UUID(project["id"]), "csv", "", "")
    collection_jobs.save_candidates(
        db, job, [Candidate("Beta", "https://group.example", "Osaka 2-2", "0612345678")]
    )
    assert db.scalar(select(func.count()).select_from(Company)) == 1
    evidence = db.scalar(
        select(LeadSourceObservation).where(LeadSourceObservation.collection_job_id == job.id)
    )
    assert (
        evidence.identity_status != "CONFIRMED"
        and evidence.facts["company_name"]["value"] == "Beta"
    )
    assert db.scalar(select(Company)).phone == ""


def test_external_source_observation_does_not_duplicate_restricted_content(auth, db):
    project = make_project(auth)
    job = collection_jobs.start_job(db, UUID(project["id"]), "google_places", "", "")
    collection_jobs.save_candidates(
        db,
        job,
        [Candidate("Synthetic shop", "https://shop.example", "City 1-1", record_type="location")],
    )
    evidence = db.scalar(select(LeadSourceObservation))
    assert evidence.facts == {} and evidence.source_url == ""
    assert evidence.allowed_usage == "REVIEW_REQUIRED" and evidence.terms_reference


def test_three_locations_one_destination_and_refresh_is_idempotent(auth, db):
    project = make_project(auth)
    import_locations(
        auth,
        project,
        [[f"Salon {i}", "https://chain.example", "", "", f"City {i}-1", ""] for i in range(3)],
    )
    rows = db.scalars(select(Company)).all()
    for row in rows:
        row.contact_url = "https://chain.example/contact/"
    db.commit()
    path = f"/api/projects/{project['id']}/lead-destinations/refresh"
    for _ in range(2):
        response = auth.post(path, json={})
        assert response.status_code == 200 and response.json()["unique_destinations"] == 1
        assert not response.json()["execution_allowed"]
    assert db.scalar(select(func.count()).select_from(Company)) == 3
    assert db.scalar(select(func.count()).select_from(ContactDestination)) == 1
    assert db.scalar(select(func.count()).select_from(LeadDestinationLink)) == 3
    result = auth.get(f"/api/companies/{rows[0].id}/lead-completion").json()
    assert (
        result["destinations"][0]["shared"] and result["destinations"][0]["linked_lead_count"] == 3
    )
    assert not result["dm_ready"] and not result["destinations"][0]["execution_allowed"]
    rows[0].contact_url = "https://chain.example/Other"
    db.commit()
    assert not auth.get(f"/api/companies/{rows[0].id}/lead-completion").json()["destinations"][0][
        "current"
    ]
    assert auth.post(path, json={"confirmed": True}).status_code == 422


def test_site_evidence_is_invalidated_by_identity_change(auth, db):
    project = make_project(auth)
    import_locations(auth, project, [["Salon ABC", "https://abc.example", "", "", "City 1-1", ""]])
    row = db.scalar(select(Company))
    db.add(
        LeadSiteEvidence(
            company_id=row.id,
            source_url=row.website_url,
            identity_hash=identity_hash(row),
            confidence="CONFIRMED",
            reasons=["COMPANY_NAME_MATCH", "ADDRESS_MATCH"],
        )
    )
    db.commit()
    path = f"/api/companies/{row.id}/lead-completion"
    assert auth.get(path).json()["official_site_confidence"] == "CONFIRMED"
    row.address = "Other 2-2"
    db.commit()
    assert auth.get(path).json()["official_site_confidence"] == "REVIEW_REQUIRED"


def test_project_boundary_is_enforced_at_api_and_database(auth, db, users):
    first = make_project(auth)
    second = make_project(auth)
    import_locations(
        auth, first, [["Alpha", "https://alpha.example", "", "a@alpha.example", "City 1-1", ""]]
    )
    import_locations(
        auth, second, [["Beta", "https://beta.example", "", "b@beta.example", "City 2-2", ""]]
    )
    company = db.scalar(select(Company).where(Company.project_id == UUID(first["id"])))
    auth.post(f"/api/projects/{second['id']}/lead-destinations/refresh", json={})
    destination = db.scalar(select(ContactDestination))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(LeadDestinationLink(company_id=company.id, destination_id=destination.id))
        db.flush()
    from app.models import Project

    other = db.get(Project, UUID(first["id"]))
    other.user_id = users[1].id
    db.commit()
    path = f"/api/companies/{company.id}/lead-completion"
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=other.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(path).json()["can_refresh"] is False
    assert (
        auth.post(f"/api/projects/{other.id}/lead-destinations/refresh", json={}).status_code == 404
    )
    assert auth.get(path, headers={"Authorization": "Bearer invalid-agent"}).status_code == 403


def test_nonempty_evidence_downgrade_is_refused(auth, db):
    project = make_project(auth)
    import_locations(auth, project, [["Alpha", "https://alpha.example", "", "", "City 1-1", ""]])
    module = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "migrations/versions/0596f0531982_lead_completion_evidence_and_.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="evidence exists"):
            module["downgrade"]()
    assert db.scalar(select(func.count()).select_from(LeadSourceObservation)) == 1


def test_identity_rules_and_query_bound():
    left = Candidate("Alpha", "https://shared.example", "City 1-1", "0612345678")
    assert compare(left, Candidate("Other", "https://shared.example"))[0] == "REVIEW_REQUIRED"
    assert compare(left, Candidate("Alpha", address="City 1-1"))[0] == "CONFIRMED"
    left.city = "City"
    assert len(site_queries(left)) <= 3
