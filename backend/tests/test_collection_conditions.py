from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    CollectionConditionRequest,
    Company,
    EmailDelivery,
    ExternalPresence,
    ExternalPresenceSearch,
    FormDelivery,
    LeadSiteEvidence,
    OperationJob,
    Project,
    ProjectMember,
    RawBenchmark,
)
from app.schema_collection_conditions import (
    CollectionCondition,
    ConfirmCollectionConditions,
    required_presence_plan,
)
from app.services.collection import Candidate
from app.services.collection_conditions import classification, evaluate, snapshot_hash
from app.services.collection_jobs import save_candidates, start_job
from app.services.external_presence import capture_url, set_status
from app.services.lead_identity import identity_hash
from tests.test_collection import make_project


def condition(priority="MUST", value="INSTAGRAM", kind="MEDIA_EXISTS", key="c1"):
    return CollectionCondition(
        id=key,
        priority=priority,
        type=kind,
        operator="EXISTS" if kind in {"MEDIA_EXISTS", "OFFICIAL_SITE"} else "EQUALS",
        value=value,
    )


@pytest.fixture
def sample(db, auth):
    project = db.get(Project, make_project(auth)["id"])
    job = start_job(db, project.id, "serper", "test", "test")
    save_candidates(db, job, [Candidate("テスト店舗", "https://example.test", phone="0791234567")])
    company = db.scalar(select(Company).where(Company.project_id == project.id))
    return project, job, company


def payload(conditions=None, version=0, **kwargs):
    return dict(
        conditions=[c.model_dump() for c in (conditions or [condition()])],
        expected_version=version,
        confirmed=True,
        **kwargs,
    )


@pytest.mark.parametrize(
    "priority,outcome,expected",
    [
        ("MUST", "MATCH", "MATCH"),
        ("MUST", "NO_MATCH", "NO_MATCH"),
        ("MUST", "UNKNOWN", "REVIEW_REQUIRED"),
        ("EXCLUDE", "MATCH", "NO_MATCH"),
        ("EXCLUDE", "NO_MATCH", "MATCH"),
        ("EXCLUDE", "UNKNOWN", "REVIEW_REQUIRED"),
        ("WANT", "MATCH", "MATCH"),
        ("WANT", "NO_MATCH", "MATCH"),
        ("WANT", "UNKNOWN", "MATCH"),
    ],
)
def test_priority_truth_table(priority, outcome, expected):
    assert classification([dict(priority=priority, outcome=outcome)]) == expected


def test_and_and_hard_failure_precedence():
    assert (
        classification(
            [dict(priority="MUST", outcome="MATCH"), dict(priority="MUST", outcome="UNKNOWN")]
        )
        == "REVIEW_REQUIRED"
    )
    assert (
        classification(
            [dict(priority="MUST", outcome="NO_MATCH"), dict(priority="EXCLUDE", outcome="UNKNOWN")]
        )
        == "NO_MATCH"
    )


def test_schema_bounds_contradictions_and_required():
    plan = required_presence_plan([condition(), condition("WANT", "X", key="c2")])
    assert plan.mode("INSTAGRAM") == "REQUIRED" and plan.mode("X") == "AUTO"
    for data in [
        payload([condition(), condition("EXCLUDE", key="c2")]),
        payload([condition()] * 21),
        {**payload(), "confirmed": False},
        {**payload(), "unknown": True},
    ]:
        with pytest.raises(ValidationError):
            ConfirmCollectionConditions.model_validate(data)
    with pytest.raises(ValidationError):
        condition(value="INVALID_PLATFORM")


def test_presence_unknown_fresh_stale_and_identity(db, sample):
    project, job, company = sample
    assert evaluate(db, company, [condition()])["state"] == "REVIEW_REQUIRED"
    capture_url(
        db,
        project.id,
        "https://instagram.com/fixture",
        company.website_url,
        company=company,
        job=job,
    )
    assert evaluate(db, company, [condition()])["state"] == "MATCH"
    row = db.scalar(select(ExternalPresence).where(ExternalPresence.company_id == company.id))
    row.observed_at = datetime.now(timezone.utc) - timedelta(days=2)
    assert evaluate(db, company, [condition()])["conditions"][0]["reason"] == "EVIDENCE_EXPIRED"
    row.observed_at = datetime.now(timezone.utc)
    company.company_name = "別店舗"
    assert evaluate(db, company, [condition()])["conditions"][0]["reason"] == "ENTITY_CHANGED"


def test_negative_requires_completed_fresh_search(db, sample):
    _, job, company = sample
    set_status(db, company, "INSTAGRAM", "NOT_FOUND", reason="SEARCH_NO_MATCH")
    assert evaluate(db, company, [condition()])["state"] == "REVIEW_REQUIRED"
    attempt = ExternalPresenceSearch(
        collection_job_id=job.id,
        budget_job_id=job.id,
        company_id=company.id,
        platform="INSTAGRAM",
        status="COMPLETED",
        created_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.flush()
    assert evaluate(db, company, [condition()])["state"] == "NO_MATCH"
    attempt.created_at -= timedelta(days=2)
    assert evaluate(db, company, [condition()])["state"] == "REVIEW_REQUIRED"


def test_official_site_url_alone_never_confirms(db, sample):
    _, _, company = sample
    c = condition(value="OFFICIAL_SITE", kind="OFFICIAL_SITE")
    assert evaluate(db, company, [c])["state"] == "REVIEW_REQUIRED"
    evidence = LeadSiteEvidence(
        company_id=company.id,
        source_url=company.website_url,
        identity_hash=identity_hash(company),
        confidence="CONFIRMED",
        reasons=["RULE"],
        observed_at=datetime.now(timezone.utc),
    )
    db.add(evidence)
    db.flush()
    assert evaluate(db, company, [c])["state"] == "MATCH"
    evidence.observed_at -= timedelta(days=2)
    assert evaluate(db, company, [c])["state"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("kind", ["AREA", "INDUSTRY", "ACTIVE_JOB", "UNRESOLVED"])
def test_unsupported_conditions_unknown(db, sample, kind):
    _, _, company = sample
    company.address = "姫路市"
    assert (
        evaluate(db, company, [condition(kind=kind, value="姫路市")])["state"] == "REVIEW_REQUIRED"
    )


def test_immutable_revisions_paging_read_only_and_hash(db, auth, sample, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "outbound_enabled", False)
    project, _, _ = sample
    base = f"/api/projects/{project.id}/collection-conditions"
    first = auth.post(base, json=payload()).json()
    assert first["version"] == 1
    assert first["payload_hash"] == snapshot_hash(first["snapshot"])
    assert auth.post(base, json=payload()).status_code == 409
    second = auth.post(base, json=payload([condition("WANT")], version=1)).json()
    assert second["version"] == 2
    assert (
        db.get(CollectionConditionRequest, first["id"]).snapshot["conditions"][0]["priority"]
        == "MUST"
    )
    count = db.scalar(select(func.count()).select_from(OperationJob))
    before = {
        m: db.scalar(select(func.count()).select_from(m))
        for m in (ApprovalRequest, EmailDelivery, FormDelivery)
    }
    result = auth.get(f"/api/collection-conditions/{second['id']}/results?limit=1").json()
    assert result["page_counts"]["MATCH"] == 1
    assert result["candidates"][0]["want_unknown"] == 1
    assert (
        auth.get(f"/api/collection-conditions/{second['id']}/results?offset=1").json()[
            "evaluated_count"
        ]
        == 0
    )
    assert db.scalar(select(func.count()).select_from(OperationJob)) == count
    assert all(db.scalar(select(func.count()).select_from(m)) == n for m, n in before.items())
    assert not settings.outbound_enabled
    row = db.get(CollectionConditionRequest, second["id"])
    row.payload_hash = "invalid"
    db.commit()
    assert auth.get(f"/api/collection-conditions/{row.id}/results").status_code == 409


def test_project_viewer_agent_and_raw_boundaries(db, auth, sample, users):
    project, _, _ = sample
    base = f"/api/projects/{project.id}/collection-conditions"
    row = auth.post(base, json=payload()).json()
    assert (
        auth.post(
            base, json=payload(version=1), headers={"Authorization": "Bearer agent"}
        ).status_code
        == 403
    )
    assert auth.get(base, headers={"Authorization": "Bearer agent"}).status_code == 403
    project.user_id = users[1].id
    db.commit()
    assert auth.get(f"/api/collection-conditions/{row['id']}/results").status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(base).status_code == 200
    assert auth.post(base, json=payload(version=1)).status_code == 404
    assert auth.get(f"/api/collection-conditions/{row['id']}/results").status_code == 200


def test_raw_benchmark_cannot_confirm_normal_conditions(db, auth, sample, users):
    project, _, _ = sample
    db.add(
        RawBenchmark(
            project_id=project.id,
            created_by_user_id=users[0].id,
            region="test",
            industry="test",
            code_commit="test",
        )
    )
    db.commit()
    assert (
        auth.post(f"/api/projects/{project.id}/collection-conditions", json=payload()).status_code
        == 409
    )


def test_collection_scope_not_all_project_and_missing_job(db, auth, sample):
    project, job, _ = sample
    base = f"/api/projects/{project.id}/collection-conditions"
    row = auth.post(base, json=payload(collection_job_id=str(job.id))).json()
    other = make_project(auth)
    other_job = start_job(db, other["id"], "serper", "x", "y")
    assert (
        auth.post(base, json=payload(version=1, collection_job_id=str(other_job.id))).status_code
        == 404
    )
    assert (
        auth.get(f"/api/collection-conditions/{row['id']}/results").json()["total_candidates"] == 1
    )
    db.delete(job)
    db.commit()
    assert auth.get(f"/api/collection-conditions/{row['id']}/results").status_code == 409
