from datetime import datetime, timedelta, timezone

import pytest

from app.models import LeadSiteEvidence, SiteIdentityReviewEvent
from app.services.collection_conditions import evaluate
from app.services.collection_fact_reviews import result
from app.services.lead_identity import identity_hash
from app.services.region_condition import compare_region
from tests import test_collection_conditions as condition_tests
from tests.test_collection_conditions import condition
from tests.test_collection_fact_reviews import payload


@pytest.fixture
def sample(db, auth):
    project, job, company = condition_tests.sample.__wrapped__(db, auth)
    company.address = "兵庫県姫路市本町1"
    company.prefecture, company.city = "兵庫県", "姫路市"
    company.website_text = company.company_name + " 所在地 " + company.address
    db.commit()
    return project, job, company


def evidence(db, company, **changes):
    values = dict(
        company_id=company.id,
        identity_hash=identity_hash(company),
        confidence="CONFIRMED",
        reasons=["ADDRESS_MATCH", "COMPANY_NAME_MATCH"],
        source_url="https://example.test/about",
        observed_at=datetime.now(timezone.utc),
    )
    row = LeadSiteEvidence(**{**values, **changes})
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize(
    "value,outcome",
    [
        ("兵庫県", "MATCH"),
        ("兵庫県姫路市", "MATCH"),
        ("兵庫県 / 姫路市", "MATCH"),
        ("大阪府", "NO_MATCH"),
        ("兵庫県神戸市", "NO_MATCH"),
        ("姫路市", "UNKNOWN"),
        ("兵庫県姫路市本町", "UNKNOWN"),
        ("兵庫県神戸市または姫路市", "UNKNOWN"),
        ("全国", "UNKNOWN"),
        ("兵/庫/県姫路市", "UNKNOWN"),
    ],
)
def test_verified_address_predicates(db, sample, value, outcome):
    _, _, company = sample
    assert result(db, company, "AREA", value)["outcome"] == "UNKNOWN"
    evidence(db, company)
    found = evaluate(db, company, [condition(value=value, kind="AREA")])["conditions"][0]
    assert found["outcome"] == outcome
    assert found["review_version"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        dict(reasons=["PHONE_MATCH", "COMPANY_NAME_MATCH"]),
        dict(confidence="HIGH"),
        dict(observed_at=datetime.now(timezone.utc) - timedelta(hours=25)),
        dict(observed_at=datetime.now(timezone.utc) + timedelta(hours=1)),
        dict(identity_hash="0" * 64),
        dict(source_url="https://unrelated.test/about"),
    ],
)
def test_bad_proof_is_unknown(db, sample, changes):
    _, _, company = sample
    evidence(db, company, **changes)
    assert result(db, company, "AREA", "兵庫県姫路市")["outcome"] == "UNKNOWN"


def test_context_conflict_latest_evidence_and_location(db, sample):
    _, _, company = sample
    evidence(db, company)
    company.city = "神戸市"
    db.commit()
    assert result(db, company, "AREA", "兵庫県姫路市")["reason"] == "REGION_ADDRESS_CONFLICT"
    company.city = "姫路市"
    evidence(db, company, confidence="REVIEW_REQUIRED")
    assert result(db, company, "AREA", "兵庫県姫路市")["outcome"] == "UNKNOWN"
    company.record_type = "location"
    company.location_key = "a" * 64
    db.commit()
    evidence(db, company)
    assert (
        result(db, company, "AREA", "兵庫県姫路市")["reason"] == "REGION_LOCATION_REVIEW_REQUIRED"
    )


def test_human_predicate_precedence_no_revival(auth, db, sample):
    _, _, company = sample
    evidence(db, company)
    url = f"/api/companies/{company.id}/collection-fact-reviews"
    assert (
        auth.post(url, json=payload(company, value="兵庫県姫路市", outcome="NO_MATCH")).status_code
        == 201
    )
    assert result(db, company, "AREA", "兵庫県姫路市")["outcome"] == "NO_MATCH"
    assert (
        auth.post(
            url, json=payload(company, value="兵庫県姫路市", outcome="UNKNOWN", version=1)
        ).status_code
        == 201
    )
    assert result(db, company, "AREA", "兵庫県姫路市")["reason"] == "FACT_REVIEW_WITHDRAWN"
    assert (
        result(
            db, company, "AREA", "兵庫県姫路市", datetime.now(timezone.utc) + timedelta(hours=25)
        )["outcome"]
        == "UNKNOWN"
    )
    assert result(db, company, "INDUSTRY", "美容院")["outcome"] == "UNKNOWN"


def test_human_site_address_reuse_and_revocation(db, sample):
    project, _, company = sample
    now = datetime.now(timezone.utc)
    row = SiteIdentityReviewEvent(
        project_id=project.id,
        company_id=company.id,
        actor_user_id=project.user_id,
        version=1,
        event_type="CONFIRMED",
        identity_hash=identity_hash(company),
        source_url="https://example.test/about",
        observed_name=company.company_name,
        observed_address=company.address,
        observed_phone="",
        evidence_excerpt="公式ページでこの店舗の所在地を確認しました",
        reasons=["ADDRESS_MATCH"],
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    company.record_type = "location"
    company.location_key = "b" * 64
    row.identity_hash = identity_hash(company)
    db.add(row)
    db.commit()
    assert result(db, company, "AREA", "兵庫県姫路市")["outcome"] == "MATCH"
    db.add(
        SiteIdentityReviewEvent(
            project_id=project.id,
            company_id=company.id,
            actor_user_id=project.user_id,
            version=2,
            event_type="REVOKED",
            identity_hash=identity_hash(company),
            source_url=row.source_url,
            observed_name=row.observed_name,
            observed_address=row.observed_address,
            observed_phone="",
            evidence_excerpt="公式サイトの所在地確認を取り消します",
            reasons=[],
            created_at=now + timedelta(microseconds=1),
            expires_at=now + timedelta(days=1),
        )
    )
    db.commit()
    evidence(db, company)
    assert result(db, company, "AREA", "兵庫県姫路市")["outcome"] == "UNKNOWN"


def test_incomplete_city_prefix_is_not_a_match(sample):
    _, _, company = sample
    company.address, company.prefecture, company.city = "三重県四日市市本町1", "三重県", "四日市"
    assert compare_region(company, "三重県四日市")[0] == "UNKNOWN"


@pytest.mark.parametrize(
    "priority,state", [("MUST", "MATCH"), ("EXCLUDE", "NO_MATCH"), ("WANT", "MATCH")]
)
def test_region_priority_and_removed_text(db, sample, priority, state):
    _, _, company = sample
    evidence(db, company)
    rule = condition(priority=priority, value="兵庫県姫路市", kind="AREA")
    assert evaluate(db, company, [rule])["state"] == state
    company.website_text = "住所の記載を削除したページ"
    db.commit()
    assert result(db, company, "AREA", rule.value)["outcome"] == "UNKNOWN"
    assert evaluate(db, company, [rule])["state"] == (
        "MATCH" if priority == "WANT" else "REVIEW_REQUIRED"
    )


def test_identity_change_invalidates_address(db, sample):
    _, _, company = sample
    evidence(db, company)
    company.company_name = "同名の別企業ではないことを未確認"
    db.commit()
    assert result(db, company, "AREA", "兵庫県姫路市")["outcome"] == "UNKNOWN"
