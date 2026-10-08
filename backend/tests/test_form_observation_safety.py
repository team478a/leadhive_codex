"""Core restrictions use synthetic stored observations; no external execution."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import ApprovalRequest, EmailDelivery, FormDelivery, FormProfile, SuppressionEntry
from app.services import form_observation_safety as safety
from app.services.contact_permission import evaluate_contact_permission
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_observation_storage import receipt as receipt
from tests.test_form_observation_storage import store


def ready(db, receipt):
    company = receipt[1]
    profile = FormProfile(
        company_id=company.id,
        form_url=company.contact_url,
        is_primary=True,
        form_found=True,
        form_status="READY",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        delivery_supported=True,
    )
    db.add(profile)
    db.commit()
    return company


def decision(db, company):
    return evaluate_contact_permission(
        db, company.project_id, company.id, "form", company.contact_url
    )


def test_saved_unverified_observation_overrides_ready_and_is_read_only(db, receipt, users):
    company = ready(db, receipt)
    assert decision(db, company).allowed
    row = store.save(db, receipt[3], users[0])
    db.commit()
    original = row.snapshot_hash
    for _ in range(2):
        assert decision(db, company).reason_code == "form_observation_review"
        assert not decision(db, company).allowed
    assert row.snapshot_hash == original
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    # Observation applies to this project/company only, and not to email.
    company.email = "safe@example.com"
    db.commit()
    assert evaluate_contact_permission(
        db, company.project_id, company.id, "email", company.email
    ).allowed


@pytest.mark.parametrize(
    "diagnostic,status,reason",
    [
        (
            {
                "sales_permission": "PROHIBITED",
                "decision": "BLOCKED",
                "captcha_state": "UNVERIFIED",
            },
            "PROHIBITED",
            "form_sales_prohibited",
        ),
        (
            {
                "sales_permission": "UNCERTAIN",
                "decision": "HUMAN_REQUIRED",
                "captcha_state": "DETECTED",
            },
            "UNCERTAIN",
            "form_captcha_review",
        ),
        (
            {
                "sales_permission": "UNCERTAIN",
                "decision": "HUMAN_REQUIRED",
                "captcha_state": "UNVERIFIED",
            },
            "UNCERTAIN",
            "form_observation_review",
        ),
    ],
)
def test_negative_projection_does_not_grant_permission(
    db, receipt, users, monkeypatch, diagnostic, status, reason
):
    company = ready(db, receipt)
    store.save(db, receipt[3], users[0])
    db.commit()
    monkeypatch.setattr(
        safety,
        "project_record",
        lambda *a, **k: SimpleNamespace(
            freshness="CURRENT", diagnostic=SimpleNamespace(**diagnostic)
        ),
    )
    result = decision(db, company)
    assert (result.status, result.reason_code) == (status, reason)
    assert not result.allowed


@pytest.mark.parametrize("freshness", ["EXPIRED", "SOURCE_CHANGED", "RETIRED", "INVALID"])
def test_stale_or_invalid_evidence_never_unlocks_ready(db, receipt, users, monkeypatch, freshness):
    company = ready(db, receipt)
    store.save(db, receipt[3], users[0])
    db.commit()
    project = safety.project_record

    def stale(row, **kwargs):
        result = project(row, **kwargs)
        return result.model_copy(update={"freshness": freshness, "diagnostic": None})

    monkeypatch.setattr(safety, "project_record", stale)
    assert decision(db, company).reason_code == "form_observation_review"


def test_real_source_change_and_retirement_remain_review(db, receipt, users):
    company = ready(db, receipt)
    row = store.save(db, receipt[3], users[0])
    db.commit()
    company.website_url = "https://managed.example/changed/"
    db.commit()
    assert decision(db, company).reason_code == "form_observation_review"
    store.retire(db, row.id, users[0], expected_hash=row.snapshot_hash)
    db.commit()
    assert decision(db, company).reason_code == "form_observation_review"


def test_existing_hard_blocks_keep_priority_and_old_schema_compatible(
    db, receipt, users, monkeypatch
):
    company = ready(db, receipt)
    store.save(db, receipt[3], users[0])
    db.commit()
    company.do_not_contact = True
    db.commit()
    assert decision(db, company).reason_code == "company_do_not_contact"
    company.do_not_contact = False
    db.add(SuppressionEntry(project_id=company.project_id, domain=company.domain, reason="stop"))
    db.commit()
    assert decision(db, company).reason_code == "suppression_domain"
    monkeypatch.setattr(safety, "storage_available", lambda db: False)
    assert safety.observation_hold(db, company) is None


@pytest.mark.parametrize(
    "suffix,status,reason",
    [
        ("<p>営業目的のお問い合わせはお断り</p>", "PROHIBITED", "form_sales_prohibited"),
        (
            "<script src='https://captcha.example/widget.js'></script>",
            "UNCERTAIN",
            "form_captcha_review",
        ),
    ],
)
def test_html_to_storage_to_core_negative_guard(db, receipt, users, suffix, status, reason):
    from tests.test_form_observation_storage import HTML, contract

    company = ready(db, receipt)
    old = receipt[3].snapshot
    envelope = contract.build(
        old.binding,
        evidence_id=old.evidence_id,
        body=(HTML + suffix).encode(),
        robots=b"User-agent: *\nAllow: /\n",
        pinned_ips=("8.8.8.8", "8.8.8.8"),
        media_type="text/html",
        started_at=old.started_at,
        observed_at=old.observed_at,
        now=old.observed_at,
    )
    store.save(db, envelope, users[0])
    db.commit()
    result = decision(db, company)
    assert (result.status, result.reason_code) == (status, reason)
    assert not result.allowed
    # A different Company in the same project does not inherit this hold.
    from app.models import Company

    other = Company(
        project_id=company.project_id, company_name="Other", source="url", domain="other.example"
    )
    db.add(other)
    db.commit()
    assert safety.observation_hold(db, other) is None


def test_observation_is_checked_without_a_form_profile(db, receipt, users):
    store.save(db, receipt[3], users[0])
    db.commit()
    assert decision(db, receipt[1]).reason_code == "form_observation_review"
