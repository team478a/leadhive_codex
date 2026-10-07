from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    Company,
    ExternalPresence,
    ExternalPresenceEvidence,
    ExternalPresenceSearch,
    Project,
    ProjectMember,
)
from app.schema_external_presence import PresenceSearchPlan
from app.services import collection
from app.services.collection import Candidate, ExternalServiceError
from app.services.collection_jobs import save_candidates, start_job
from app.services.external_presence import capture_url, extra_searches, inventory
from app.services.presence_platforms import classify
from tests.test_collection import make_project


@pytest.fixture
def sample(db, auth):
    p = make_project(auth)
    project = db.get(Project, p["id"])
    job = start_job(db, project.id, "serper", "美容院", "姫路市")
    candidate = Candidate("テスト美容室", "https://salon.example", phone="0791234567")
    save_candidates(db, job, [candidate])
    company = db.scalar(select(Company).where(Company.project_id == project.id))
    return project, job, company


def status(db, company, platform="INSTAGRAM"):
    return next(r for r in inventory(db, company.id) if r["platform"] == platform)


def test_off_captures_passive_and_deduplicates(db, sample, monkeypatch):
    project, job, company = sample

    def forbidden(*args):
        raise AssertionError("OFF must not search")

    monkeypatch.setattr(collection, "search_serper", forbidden)
    for _ in range(2):
        capture_url(
            db,
            project.id,
            "https://instagram.com/testsalon",
            company.website_url,
            company=company,
            job=job,
        )
    extra_searches(db, job, PresenceSearchPlan())
    assert status(db, company)["status"] == "FOUND"
    assert db.scalar(select(func.count()).select_from(ExternalPresenceEvidence)) == 1
    assert status(db, company, "X")["status"] == "NOT_CHECKED"


@pytest.mark.parametrize("found,expected", [(True, "FOUND"), (False, "NOT_FOUND")])
def test_search_on(db, sample, monkeypatch, found, expected):
    _, job, company = sample
    calls = []

    def search(*args):
        calls.append(args)
        return (
            [
                Candidate(
                    "テスト美容室", "https://instagram.com/testsalon", search_excerpt="0791234567"
                )
            ]
            if found
            else []
        )

    monkeypatch.setattr(collection, "search_serper", search)
    extra_searches(db, job, PresenceSearchPlan(modes={"INSTAGRAM": "SEARCH"}))
    assert len(calls) == 1
    assert status(db, company)["status"] == expected
    assert status(db, company)["discovery_method"] == "EXPLICIT_SEARCH"
    extra_searches(db, job, PresenceSearchPlan(modes={"INSTAGRAM": "SEARCH"}))
    assert len(calls) == 1  # Committed attempts cannot be replayed.


def test_required_overrides_off(db, sample, monkeypatch):
    _, job, company = sample
    calls = []

    def search(*args):
        calls.append(args)
        return [
            Candidate(
                "テスト美容室", "https://instagram.com/testsalon", search_excerpt="0791234567"
            )
        ]

    monkeypatch.setattr(collection, "search_serper", search)
    extra_searches(
        db, job, PresenceSearchPlan(modes={"INSTAGRAM": "AUTO"}, required_platforms=["INSTAGRAM"])
    )
    assert len(calls) == 1
    assert status(db, company)["discovery_method"] == "REQUIRED_VERIFICATION"


@pytest.mark.parametrize(
    "url,platform",
    [
        ("https://beauty.hotpepper.jp/slnH000001", "HOTPEPPER_BEAUTY"),
        ("https://jp.indeed.com/company/testsalon", "INDEED"),
        ("https://x.com/testsalon", "X"),
        ("https://youtube.com/@testsalon", "YOUTUBE"),
    ],
)
def test_passive_media_capture(db, sample, url, platform):
    project, job, company = sample
    capture_url(db, project.id, url, company.website_url, company=company, job=job)
    row = status(db, company, platform)
    assert row["status"] == "FOUND"
    assert row["url"] == url
    assert row["discovery_method"] == "PASSIVE"


def test_company_link_is_not_assumed_from_portal_search(db, sample):
    project, job, _ = sample
    candidate = Candidate("同名店舗", "https://beauty.hotpepper.jp/slnH000099")
    save_candidates(db, job, [candidate])
    evidence = db.scalar(select(ExternalPresenceEvidence))
    assert evidence.project_id == project.id
    assert evidence.company_id is None
    assert evidence.association == "REVIEW_REQUIRED"
    assert job.excluded_count == 1  # A listing page is not itself a Company.


def test_budget_bounds_and_required_first(db, sample, monkeypatch):
    _, job, company = sample
    calls = []

    def search(*args):
        calls.append(args)
        return []

    monkeypatch.setattr(collection, "search_serper", search)
    extra_searches(
        db,
        job,
        PresenceSearchPlan(
            modes={"X": "SEARCH", "INSTAGRAM": "SEARCH"},
            required_platforms=["YOUTUBE"],
            max_extra_searches=1,
        ),
    )
    assert len(calls) == 1 and "youtube.com" in calls[0][0]
    assert status(db, company)["status"] == "ERROR"
    assert status(db, company)["reason"] == "SEARCH_BUDGET_EXHAUSTED"


def test_budget_shared_across_queries(db, sample, monkeypatch):
    project, job, company = sample
    calls = []

    def search(*args):
        calls.append(args)
        return []

    monkeypatch.setattr(collection, "search_serper", search)
    plan = PresenceSearchPlan(modes={"INSTAGRAM": "SEARCH"}, max_extra_searches=1)
    extra_searches(db, job, plan)
    second = start_job(db, project.id, "serper", "美容室", "姫路市")
    save_candidates(
        db, second, [Candidate(company.company_name, company.website_url, phone=company.phone)]
    )
    extra_searches(db, second, plan, budget_job_id=job.id)
    assert len(calls) == 1


def test_timeout_and_error_are_not_absence(db, sample, monkeypatch):
    _, job, company = sample
    job.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    monkeypatch.setattr(collection, "search_serper", lambda *a: pytest.fail("timeout"))
    extra_searches(db, job, PresenceSearchPlan(modes={"INSTAGRAM": "SEARCH"}))
    assert status(db, company)["status"] == "ERROR"
    job.created_at = datetime.now(timezone.utc)

    def fail(*args):
        raise ExternalServiceError("test failure")

    monkeypatch.setattr(collection, "search_serper", fail)
    extra_searches(db, job, PresenceSearchPlan(modes={"INSTAGRAM": "SEARCH"}))
    assert status(db, company)["reason"] == "SEARCH_FAILED"
    assert db.scalar(select(func.count()).select_from(ExternalPresenceSearch)) == 1


def test_name_only_result_needs_review(db, sample, monkeypatch):
    _, job, company = sample
    monkeypatch.setattr(
        collection,
        "search_serper",
        lambda *a: [Candidate(company.company_name, "https://instagram.com/other")],
    )
    extra_searches(db, job, PresenceSearchPlan(modes={"INSTAGRAM": "SEARCH"}))
    assert status(db, company)["status"] == "ERROR"
    assert status(db, company)["reason"] == "ENTITY_UNCERTAIN"


def test_entity_change_invalidates_presence(db, sample):
    project, job, company = sample
    capture_url(
        db,
        project.id,
        "https://instagram.com/testsalon",
        company.website_url,
        company=company,
        job=job,
    )
    assert status(db, company)["status"] == "FOUND"
    company.phone = "0799999999"
    assert status(db, company)["status"] == "ERROR"
    assert status(db, company)["reason"] == "ENTITY_CHANGED"


def test_multiple_socials_and_unknown_modes(db, sample):
    project, job, company = sample
    for url in [
        "https://instagram.com/testsalon",
        "https://x.com/testsalon",
        "https://youtube.com/@testsalon",
    ]:
        for _ in range(2):
            capture_url(db, project.id, url, company.website_url, company=company, job=job)
    assert db.scalar(select(func.count()).select_from(ExternalPresence)) == 3
    with pytest.raises(ValueError):
        PresenceSearchPlan(modes={"UNKNOWN_PLATFORM": "SEARCH"})
    with pytest.raises(ValueError):
        PresenceSearchPlan(max_extra_searches=31)


def test_cross_project_and_places_retention_guard(db, sample, monkeypatch):
    project, job, company = sample
    with pytest.raises(ValueError):
        capture_url(
            db, company.id, "https://instagram.com/testsalon", company.website_url, company=company
        )
    job.source = "google_places"
    capture_url(
        db,
        project.id,
        "https://instagram.com/testsalon",
        company.website_url,
        company=company,
        job=job,
    )
    assert status(db, company)["status"] == "NOT_CHECKED"
    monkeypatch.setattr(
        collection, "search_serper", lambda *a: pytest.fail("Places terms unreviewed")
    )
    extra_searches(db, job, PresenceSearchPlan(modes={"INSTAGRAM": "SEARCH"}))
    assert status(db, company)["reason"] == "SOURCE_TERMS_REVIEW_REQUIRED"


def test_required_report_never_counts_unchecked_as_match(db, auth, sample):
    _, job, _ = sample
    job.presence_search_plan = PresenceSearchPlan(required_platforms=["INSTAGRAM"]).model_dump(
        mode="json"
    )
    db.commit()
    result = auth.get(f"/api/collection-jobs/{job.id}/external-presence-report")
    assert result.status_code == 200
    assert result.json()["candidates"][0]["requirement_state"] == "REVIEW_REQUIRED"


def test_old_positive_evidence_is_not_current_required_match(db, auth, sample):
    project, job, company = sample
    capture_url(
        db, project.id, "https://instagram.com/testsalon", company.website_url, company=company
    )
    presence = db.scalar(select(ExternalPresence))
    presence.observed_at = datetime.now(timezone.utc) - timedelta(days=2)
    job.presence_search_plan = PresenceSearchPlan(required_platforms=["INSTAGRAM"]).model_dump(
        mode="json"
    )
    db.commit()
    result = auth.get(f"/api/collection-jobs/{job.id}/external-presence-report")
    assert result.json()["candidates"][0]["requirement_state"] == "REVIEW_REQUIRED"


def test_automatic_capture_cannot_overwrite_human_selection(db, sample, users):
    project, job, company = sample
    original = "https://instagram.com/humanselected"
    capture_url(db, project.id, original, original, company=company, actor_user_id=users[0].id)
    capture_url(
        db,
        project.id,
        "https://instagram.com/automatic",
        company.website_url,
        company=company,
        job=job,
    )
    assert status(db, company)["url"] == original
    assert db.scalar(select(func.count()).select_from(ExternalPresenceEvidence)) == 2


def test_read_link_and_project_permissions(db, auth, sample, users):
    project, job, company = sample
    capture_url(
        db,
        project.id,
        "https://instagram.com/testsalon",
        "https://instagram.com/testsalon",
        job=job,
    )
    db.commit()
    rows = auth.get(f"/projects/{project.id}")  # Wrong API prefix cannot confer permissions.
    assert rows.status_code == 404
    base = f"/api/projects/{project.id}/external-presence-evidence"
    evidence = auth.get(base).json()[0]
    assert (
        auth.post(
            f"/api/external-presence-evidence/{evidence['id']}/link",
            json=dict(company_id=str(company.id), expected_url=evidence["url"], confirmed=True),
        ).status_code
        == 200
    )
    assert (
        auth.get(f"/api/companies/{company.id}/external-presences").json()[0]["url"]
        == evidence["url"]
    )
    assert auth.get(base, headers={"Authorization": "Bearer fake-agent-token"}).status_code == 403
    project.user_id = users[1].id
    db.commit()
    assert auth.get(base).status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(base).status_code == 200
    assert (
        auth.post(
            f"/api/external-presence-evidence/{evidence['id']}/link",
            json=dict(company_id=str(company.id), expected_url=evidence["url"], confirmed=True),
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://instagram.com.evil.test/account",
        "https://instagram.com/search",
        "https://instagram.com",
        "https://user:secret@instagram.com/user",
        "https://example.com/news",
        "https://instagram.com/explore/tags/salon",
    ],
)
def test_non_presence_urls_are_rejected(url):
    assert classify(url) is None
