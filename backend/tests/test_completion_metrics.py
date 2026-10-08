"""Synthetic measurement/security regression; no real provider or delivery calls."""

import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import (
    Company,
    LeadCompletionCohort,
    LeadProcessingUsage,
    LeadReviewSession,
    Project,
    ProjectMember,
)
from app.services.collection import search_google_places, search_serper
from app.services.collection_jobs import start_job
from app.services.processing_usage import measured_search
from tests.test_location_import import import_locations, make_project


def fixture_cohort(auth, db, count=3):
    project = make_project(auth)
    import_locations(
        auth,
        project,
        [[f"Shop {i}", "https://chain.example", "", "", f"City {i}-1", ""] for i in range(count)],
    )
    companies = db.scalars(select(Company).where(Company.project_id == UUID(project["id"]))).all()
    result = auth.post(
        f"/api/projects/{project['id']}/completion-cohorts", json={"name": "Fixed synthetic list"}
    )
    assert result.status_code == 201
    return project, companies, result.json()


def test_fixed_denominator_unknown_metrics_and_stale_inventory(auth, db):
    project, companies, cohort = fixture_cohort(auth, db)
    for company in companies:
        company.contact_url = "https://chain.example/contact"
    companies[0].do_not_contact = True
    db.commit()
    path = f"/api/completion-cohorts/{cohort['id']}"
    result = auth.get(path).json()
    assert result["discovered"] == 3 and result["diagnostics"]["unique_candidate_destinations"] == 1
    assert result["diagnostics"]["shared_candidate_destinations"] == 1
    assert result["diagnostics"]["states"] == {"REVIEW": 2, "HOLD": 0, "BLOCKED": 1}
    assert result["diagnostics"]["reasons"]["SHARED_DESTINATION"] == 2  # One per lead, not twice.
    assert result["dm_ready_rate"] is None and result["cost"]["estimated_total_cost"] is None
    assert result["cost"]["review_seconds"] is None and result["cost"]["cost_per_dm_ready"] is None
    assert result["stages"][4]["count"] is None  # Candidate URL is not a verified destination.
    assert not result["execution_allowed"]
    db.delete(companies[-1])
    db.commit()
    import_locations(auth, project, [["New shop", "https://new.example", "", "", "City 4-1", ""]])
    updated = auth.get(path).json()
    assert updated["discovered"] == 3 and updated["remaining_leads"] == 2
    assert updated["diagnostics"]["reasons"]["LEAD_REMOVED_OR_MERGED"] == 1
    row = db.get(LeadCompletionCohort, UUID(cohort["id"]))
    with pytest.raises(IntegrityError), db.begin_nested():
        row.company_ids = row.company_ids + [str(companies[0].id)]
        db.flush()


def test_server_review_timer_replay_stale_and_no_approval(auth, db):
    _, companies, cohort = fixture_cohort(auth, db)
    start = f"/api/completion-cohorts/{cohort['id']}/reviews"
    body = {"company_id": str(companies[0].id)}
    result = auth.post(start, json=body)
    assert result.status_code == 201
    review = result.json()
    assert auth.post(start, json=body).json()["id"] == review["id"]
    assert auth.post(start, json={"company_id": str(companies[1].id)}).status_code == 409
    path = f"/api/completion-reviews/{review['id']}/finish"
    assert auth.post(path, json={"outcome": "CHECKED", "seconds": 5}).status_code == 422
    assert auth.post(path, json={"outcome": "APPROVED"}).status_code == 422
    companies[0].contact_url = "https://chain.example/changed"
    db.commit()
    finish = auth.post(path, json={"outcome": "CHECKED"}).json()
    assert finish["outcome"] == "STALE" and 0 <= finish["duration_seconds"] < 60
    assert auth.post(path, json={"outcome": "CHECKED"}).json() == finish
    measured = auth.get(f"/api/completion-cohorts/{cohort['id']}").json()
    assert measured["cost"]["completed_reviews"] == 1 and measured["active_review"] is None
    from app.models import ApprovalRequest, EmailDelivery, FormDelivery

    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    row = db.get(LeadReviewSession, UUID(review["id"]))
    with pytest.raises(IntegrityError), db.begin_nested():
        row.outcome = "HOLD"
        db.flush()


def test_expired_review_is_abandoned_without_time_claim(auth, db):
    _, companies, cohort = fixture_cohort(auth, db)
    from app.completion_metrics_routes import review_hash

    row = LeadReviewSession(
        cohort_id=UUID(cohort["id"]),
        company_id=companies[0].id,
        user_id=db.get(Project, companies[0].project_id).user_id,
        identity_hash=review_hash(companies[0]),
        started_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    db.add(row)
    db.commit()
    result = auth.post(
        f"/api/completion-reviews/{row.id}/finish", json={"outcome": "CHECKED"}
    ).json()
    assert result["outcome"] == "ABANDONED" and result["duration_seconds"] is None


def test_project_viewer_agent_and_database_boundaries(auth, db, users):
    project, companies, cohort = fixture_cohort(auth, db)
    other_project, other_companies, other_cohort = fixture_cohort(auth, db)
    assert (
        auth.post(
            f"/api/completion-cohorts/{cohort['id']}/reviews",
            json={"company_id": str(other_companies[0].id)},
        ).status_code
        == 404
    )
    row = db.get(Project, UUID(project["id"]))
    row.user_id = users[1].id
    db.commit()
    path = f"/api/completion-cohorts/{cohort['id']}"
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=row.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(path).json()["can_review"] is False
    assert (
        auth.post(f"/api/projects/{row.id}/completion-cohorts", json={"name": "forged"}).status_code
        == 404
    )
    assert (
        auth.post(path + "/reviews", json={"company_id": str(companies[0].id)}).status_code == 404
    )
    assert auth.get(path, headers={"Authorization": "Bearer forged-agent"}).status_code == 403
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            LeadReviewSession(
                cohort_id=UUID(other_cohort["id"]),
                company_id=companies[0].id,
                user_id=users[0].id,
                identity_hash="0" * 64,
                started_at=datetime.now(timezone.utc),
            )
        )
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            LeadProcessingUsage(
                project_id=UUID(other_project["id"]),
                company_id=companies[0].id,
                kind="search",
                provider="serper",
                status="completed",
                started_at=datetime.now(timezone.utc),
                elapsed_ms=0,
            )
        )
        db.flush()


def test_real_http_attempts_pages_errors_no_secret_storage(auth, db, monkeypatch):
    project = make_project(auth)
    monkeypatch.setattr(settings, "google_places_api_key", "never-store-this-key")
    responses = [
        httpx.Response(
            200,
            json={
                "places": [{"displayName": {"text": "Synthetic shop"}}],
                "nextPageToken": "synthetic",
            },
            request=httpx.Request("POST", "https://places.googleapis.com"),
        ),
        httpx.Response(500, request=httpx.Request("POST", "https://places.googleapis.com")),
    ]

    def post(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(httpx.Client, "post", post)
    job = start_job(db, UUID(project["id"]), "google_places", "private search", "")
    from app.services.collection import ExternalServiceError

    with pytest.raises(ExternalServiceError):
        measured_search(db, job, search_google_places, "private search", "", 40)
    records = db.scalars(select(LeadProcessingUsage)).all()
    assert sorted(r.status for r in records) == ["completed", "failed"]
    assert all(r.collection_job_id == job.id and r.estimated_cost is None for r in records)
    assert not any(
        "never-store-this-key" in str(r.__dict__) or "private search" in str(r.__dict__)
        for r in records
    )
    monkeypatch.setattr(settings, "serper_api_key", "")
    with pytest.raises(ExternalServiceError):
        measured_search(db, job, search_serper, "", "", 5)
    assert (
        db.scalar(select(func.count()).select_from(LeadProcessingUsage)) == 2
    )  # No HTTP on missing key.


def test_nonempty_measurements_cannot_be_downgraded(auth, db):
    fixture_cohort(auth, db)
    module = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "migrations/versions/06a2f819c310_lead_completion_cohort_usage_and_review_.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="measurements exist"):
            module["downgrade"]()


def test_match_evidence_is_bound_to_current_analysis_and_context(auth, db):
    project, companies, cohort = fixture_cohort(auth, db, count=1)
    from app.models import LeadSiteEvidence, OperationJob, SalesPreparationItem, TargetProfile
    from app.services.lead_identity import identity_hash
    from app.services.sales_preparation import completion_match_hash, context_hash

    company = companies[0]
    company.ai_status, company.is_target, company.score = "completed", True, 90
    company.ai_analyzed_at = datetime.now(timezone.utc)
    company.email = "synthetic@example.com"
    owner = db.get(Project, UUID(project["id"]))
    profile = db.get(TargetProfile, owner.target_profile_id)
    job = OperationJob(
        project_id=owner.id,
        operation_type="prepare_outreach",
        payload={"context_hash": context_hash(owner, profile), "minimum_score": 85},
    )
    db.add(job)
    db.flush()
    db.add(
        SalesPreparationItem(
            job_id=job.id,
            company_id=company.id,
            status="ready",
            details={
                "analysis_completed": True,
                "completion_match_hash": completion_match_hash(company),
                "completion_ai_analyzed_at": str(company.ai_analyzed_at),
            },
        )
    )
    db.add(
        LeadSiteEvidence(
            company_id=company.id,
            source_url=company.website_url,
            identity_hash=identity_hash(company),
            confidence="CONFIRMED",
            reasons=["SYNTHETIC_TEST"],
        )
    )
    db.commit()
    path = f"/api/completion-cohorts/{cohort['id']}"
    result = auth.get(path).json()
    assert [stage["count"] for stage in result["stages"][:4]] == [1, 1, 1, 1]
    assert result["stages"][1]["conversion_rate"] == 100.0
    assert result["stages"][4]["count"] is None and result["dm_ready"] is None
    company.business_summary = "Changed source information"
    db.commit()
    assert auth.get(path).json()["stages"][1]["count"] == 0
    owner.sales_objective = "Changed sales objective"
    db.commit()
    assert auth.get(path).json()["context_changed"] is True
