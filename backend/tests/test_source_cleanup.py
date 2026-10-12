"""Offline source cleanup retains records, reviews and permission boundaries."""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models import Activity, AiReview, Company, ProjectMember
from app.services.collection_feedback import PREFIX as FEEDBACK_PREFIX
from app.services.source_cleanup import PREFIX
from tests.conftest import PASSWORD
from tests.test_sendability import company_fixture


def candidate(auth, db, url="https://retty.me/area", **changes):
    company = company_fixture(auth, db)
    company.record_type = "company"
    company.location_key = ""
    company.source = "serper"
    company.website_url = url
    company.domain = url.split("/")[2]
    company.status = "unreviewed"
    company.protected_fields = []
    company.contact_quality_status = "unknown"
    for key, value in changes.items():
        setattr(company, key, value)
    db.commit()
    return company


def path(company):
    return f"/api/projects/{company.project_id}/source-exclusions/cleanup"


def run(auth, company):
    return auth.post(path(company), json={"company_ids": [str(company.id)]})


def test_cleanup_reversible_idempotent_and_preserves_data(auth, db):
    company = candidate(auth, db)
    before = (company.website_url, company.contact_url, company.analysis_status, company.ai_status)
    assert run(auth, company).json()["excluded_ids"] == [str(company.id)]
    db.refresh(company)
    assert company.status == "excluded"
    assert company.do_not_contact
    from app.services.contact_permission import evaluate_contact_permission

    for channel, destination in [("email", "hello@retty.me"), ("form", company.website_url)]:
        assert not evaluate_contact_permission(
            db, company.project_id, company.id, channel, destination
        ).allowed
    assert (
        company.website_url,
        company.contact_url,
        company.analysis_status,
        company.ai_status,
    ) == before
    assert db.scalar(select(func.count()).select_from(Company)) == 1
    assert run(auth, company).json()["excluded_ids"] == []
    events = db.scalars(select(Activity).where(Activity.company_id == company.id)).all()
    assert len(events) == 1
    assert json.loads(events[0].note[len(PREFIX) :])["origin"] == "SYSTEM_RULE"
    assert auth.get(f"{path(company)}/{company.id}").json()["restorable"]
    assert (
        auth.post(
            f"{path(company)}/{company.id}/restore",
            json={"expected_updated_at": company.updated_at.isoformat()},
        ).status_code
        == 200
    )
    db.refresh(company)
    assert company.status == "unreviewed"
    assert not company.do_not_contact
    assert company.exclusion_reason == ""
    assert run(auth, company).json()["protected_ids"] == [str(company.id)]
    assert auth.get(f"{path(company)}/{company.id}").json()["restorable"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "target"},
        {"status": "approached"},
        {"status": "excluded"},
        {"do_not_contact": True},
        {"protected_fields": ["company_name"]},
        {"exclusion_reason": "人の理由"},
        {"record_type": "location", "location_key": "a" * 64},
        {"source": "csv"},
        {"contact_quality_status": "verified"},
    ],
)
def test_protected_records_are_unchanged(auth, db, changes):
    company = candidate(auth, db, **changes)
    before = company.status
    assert run(auth, company).json()["excluded_ids"] == []
    db.refresh(company)
    assert company.status == before
    assert db.scalar(select(func.count()).select_from(Activity)) == 0


@pytest.mark.parametrize("review", ["feedback", "legacy"])
def test_human_company_reviews_never_overwritten(auth, db, users, review):
    company = candidate(auth, db)
    if review == "feedback":
        db.add(
            Activity(
                company_id=company.id,
                activity_type="note",
                note=FEEDBACK_PREFIX + json.dumps({"subject": "company", "outcome": "OK"}),
            )
        )
    else:
        db.add(AiReview(company_id=company.id, reviewer_id=users[0].id, verdict="correct"))
    db.commit()
    assert run(auth, company).json()["protected_ids"] == [str(company.id)]
    db.refresh(company)
    assert company.status == "unreviewed"


@pytest.mark.parametrize(
    "url",
    [
        "https://retty.me.example.test/",
        "https://restaurant.test/?ref=retty.me",
        "https://restaurant.test/blog/recommendations",
        "",
    ],
)
def test_unknown_or_official_sites_not_automatically_removed(auth, db, url):
    company = candidate(auth, db, url or "https://restaurant.test/")
    company.website_url = url
    db.commit()
    assert run(auth, company).json()["excluded_ids"] == []


def test_project_memory_only_and_reference_url_does_not_exclude_company(auth, db):
    company = candidate(auth, db, "https://listing.example/")
    other = candidate(auth, db, "https://listing.example/")
    assert (
        auth.post(
            f"/api/projects/{company.project_id}/source-exclusions",
            json={
                "evidence_url": company.website_url,
                "reason": "掲載媒体",
                "confirmed_domain_wide": True,
            },
        ).status_code
        == 201
    )
    assert run(auth, company).json()["excluded_ids"] == [str(company.id)]
    assert run(auth, other).json()["excluded_ids"] == []
    other.reference_url = "https://retty.me/area"
    db.commit()
    assert run(auth, other).json()["excluded_ids"] == []


def test_stale_restore_and_viewer_cross_project_rejected(auth, db, users):
    company = candidate(auth, db)
    assert run(auth, company).status_code == 200
    db.refresh(company)
    timestamp = company.updated_at.isoformat()
    company.do_not_contact = True
    company.updated_at = datetime.now(timezone.utc)
    db.commit()
    assert (
        auth.post(
            f"{path(company)}/{company.id}/restore", json={"expected_updated_at": timestamp}
        ).status_code
        == 409
    )
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    auth.post("/api/auth/logout")
    assert (
        auth.post(
            "/api/auth/login", json={"email": users[1].email, "password": PASSWORD}
        ).status_code
        == 200
    )
    assert auth.get(f"{path(company)}/{company.id}").status_code == 200
    assert run(auth, company).status_code == 404
    assert (
        auth.post(
            f"{path(company)}/{company.id}/restore",
            json={"expected_updated_at": company.updated_at.isoformat()},
        ).status_code
        == 404
    )


def test_foreign_company_batch_is_atomic_and_bounded(auth, db):
    company = candidate(auth, db)
    other = candidate(auth, db)
    assert (
        auth.post(path(company), json={"company_ids": [str(company.id), str(other.id)]}).status_code
        == 404
    )
    db.refresh(company)
    assert company.status == "unreviewed"
    assert (
        auth.post(path(company), json={"company_ids": [str(company.id)] * 101}).status_code == 422
    )


def test_status_change_history_is_protected(auth, db):
    company = candidate(auth, db)
    db.add(Activity(company_id=company.id, activity_type="status_change", note="人が候補へ戻した"))
    db.commit()
    assert run(auth, company).json()["protected_ids"] == [str(company.id)]


def test_restore_requires_aware_timestamp(auth, db):
    company = candidate(auth, db)
    assert run(auth, company).status_code == 200
    assert (
        auth.post(
            f"{path(company)}/{company.id}/restore",
            json={"expected_updated_at": "2026-10-12T00:00:00"},
        ).status_code
        == 422
    )
