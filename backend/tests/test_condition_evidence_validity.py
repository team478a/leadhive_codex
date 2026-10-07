from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import ExternalPresence, ExternalPresenceSearch, SiteIdentityReviewEvent
from app.services.collection_conditions import evaluate
from app.services.external_presence import capture_url, set_status
from app.services.lead_identity import identity_hash
from tests import test_collection_conditions as conditions
from tests.test_collection_conditions import condition
from tests.test_region_condition import evidence


@pytest.fixture
def sample(db, auth):
    return conditions.sample.__wrapped__(db, auth)


def site(db, company, now):
    return evaluate(db, company, [condition(kind="OFFICIAL_SITE", value="OFFICIAL_SITE")], now)


@pytest.mark.parametrize(
    "mode", ["REVOKED", "EXPIRED", "STALE", "FUTURE", "OTHER_PROJECT", "BAD_URL"]
)
def test_human_site_invalid_never_revives_automatic(db, auth, sample, mode):
    project, _, company = sample
    now = datetime.now(timezone.utc)
    evidence(db, company, observed_at=now)
    row = SiteIdentityReviewEvent(
        project_id=project.id,
        company_id=company.id,
        actor_user_id=project.user_id,
        version=1,
        event_type="REVOKED" if mode == "REVOKED" else "CONFIRMED",
        identity_hash="0" * 64 if mode == "STALE" else identity_hash(company),
        source_url="https://unrelated.test" if mode == "BAD_URL" else company.website_url,
        observed_name=company.company_name,
        observed_address="",
        observed_phone=company.phone,
        evidence_excerpt="公式サイトの企業情報を人が確認しました",
        reasons=["PHONE_MATCH"],
        created_at=now - timedelta(days=2)
        if mode == "EXPIRED"
        else now + timedelta(hours=1)
        if mode == "FUTURE"
        else now,
        expires_at=now - timedelta(days=1) if mode == "EXPIRED" else now + timedelta(days=1),
    )
    if mode == "OTHER_PROJECT":
        from app.models import Project
        from tests.test_collection import make_project

        row.project_id = db.get(Project, make_project(auth)["id"]).id
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(row)
            db.flush()
        return  # Existing DB guard rejects cross-project evidence before evaluation.
    db.add(row)
    db.flush()
    assert site(db, company, now)["state"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("mode", ["REVIEW_REQUIRED", "WRONG_HASH", "FUTURE", "BAD_URL", "EXPIRED"])
def test_latest_automatic_proof_required(db, sample, mode):
    _, _, company = sample
    now = datetime.now(timezone.utc)
    evidence(db, company, observed_at=now - timedelta(seconds=1))
    changes = dict(observed_at=now)
    if mode == "REVIEW_REQUIRED":
        changes["confidence"] = "REVIEW_REQUIRED"
    elif mode == "WRONG_HASH":
        changes["identity_hash"] = "0" * 64
    elif mode == "FUTURE":
        changes["observed_at"] = now + timedelta(seconds=1)
    elif mode == "BAD_URL":
        changes["source_url"] = "https://unrelated.test"
    elif mode == "EXPIRED":
        # Both old and latest observations are expired at evaluation time.
        now += timedelta(days=2)
        changes["observed_at"] = now - timedelta(days=1, seconds=1)
    evidence(db, company, **changes)
    assert site(db, company, now)["state"] == "REVIEW_REQUIRED"


def test_current_human_site_uses_human_source(db, sample):
    project, _, company = sample
    now = datetime.now(timezone.utc)
    evidence(db, company, observed_at=now, confidence="REVIEW_REQUIRED")
    db.add(
        SiteIdentityReviewEvent(
            project_id=project.id,
            company_id=company.id,
            actor_user_id=project.user_id,
            version=1,
            event_type="CONFIRMED",
            identity_hash=identity_hash(company),
            source_url=company.website_url + "/about",
            observed_name=company.company_name,
            observed_address="",
            observed_phone=company.phone,
            evidence_excerpt="公式サイトの電話番号が一致することを確認しました",
            reasons=["PHONE_MATCH"],
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    db.flush()
    value = site(db, company, now)
    assert value["state"] == "MATCH"
    assert value["conditions"][0]["evidence_url"].endswith("/about")


@pytest.mark.parametrize("negative", [False, True])
def test_future_presence_is_unknown(db, sample, negative):
    project, job, company = sample
    now = datetime.now(timezone.utc)
    if negative:
        set_status(db, company, "INSTAGRAM", "NOT_FOUND", reason="SEARCH_NO_MATCH")
        db.add(
            ExternalPresenceSearch(
                collection_job_id=job.id,
                budget_job_id=job.id,
                company_id=company.id,
                platform="INSTAGRAM",
                status="COMPLETED",
                created_at=now + timedelta(hours=1),
            )
        )
    else:
        capture_url(
            db, project.id, "https://instagram.com/fixture", company.website_url, company=company
        )
    row = db.scalar(select(ExternalPresence).where(ExternalPresence.company_id == company.id))
    row.observed_at = now + timedelta(hours=1)
    db.flush()
    assert evaluate(db, company, [condition()], now)["state"] == "REVIEW_REQUIRED"


def test_future_human_fact_is_unknown(db, auth, sample):
    from app.services.collection_fact_reviews import latest, result
    from tests.test_collection_fact_reviews import payload

    _, _, company = sample
    assert (
        auth.post(
            f"/api/companies/{company.id}/collection-fact-reviews",
            json=payload(company, value="姫路市"),
        ).status_code
        == 201
    )
    row = latest(db, company, "AREA", "姫路市")
    assert (
        result(db, company, "AREA", "姫路市", row.created_at - timedelta(seconds=1))["reason"]
        == "EVIDENCE_FUTURE"
    )
