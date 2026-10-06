"""Synthetic, cached diagnostics only. No provider, approval or delivery execution."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    Company,
    ContactDestination,
    ContactPerson,
    EmailDelivery,
    FormDelivery,
    FormProfile,
    FormProfileField,
    LeadSiteEvidence,
    OutreachDraft,
    Project,
    ProjectMember,
    SuppressionEntry,
)
from app.services.contact_destinations import sync_company
from app.services.lead_identity import identity_hash
from app.services.sendability import evaluate
from tests.test_location_import import import_locations, make_project


def company_fixture(auth, db, email=""):
    project = make_project(auth)
    import_locations(
        auth, project, [["Synthetic shop", "https://shop.example", "", email, "City 1-1", ""]]
    )
    return db.scalar(select(Company).where(Company.project_id == UUID(project["id"])))


def profile_fixture(db, company, **changes):
    values = dict(
        company_id=company.id,
        form_url="https://shop.example/contact",
        form_status="READY",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        is_primary=True,
        form_found=True,
        delivery_supported=True,
        fingerprint="f" * 64,
        last_analyzed_at=datetime.now(timezone.utc),
    )
    values.update(changes)
    profile = FormProfile(**values)
    db.add(profile)
    db.flush()
    db.add(
        FormProfileField(
            form_profile_id=profile.id,
            position=0,
            field_type="textarea",
            mapped_key="message",
            confidence=1,
        )
    )
    db.commit()
    return profile


def codes(row):
    return {r["code"] for r in row["reasons"]}


def test_technical_ready_is_not_dm_ready_or_human_approval(auth, db):
    company = company_fixture(auth, db)
    profile_fixture(db, company)
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
    sync_company(db, company)
    destination = db.scalar(select(ContactDestination))
    destination.purpose = "sales"  # Unbound metadata is NOT an attestation.
    destination.scope = "location"
    db.commit()
    path = f"/api/companies/{company.id}/sendability"
    for _ in range(2):
        response = auth.get(path)
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "REVIEW"
        assert codes(result) == {"DESTINATION_PURPOSE_UNCERTAIN"}
        assert not result["execution_allowed"] and not result["dm_ready"]
        assert not result["live_destination_checked"]
        assert result["recommended_destination"] is None
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert db.scalar(select(func.count()).select_from(ContactDestination)) == 1
    company.address = "Changed 2-2"
    db.commit()
    assert "IDENTITY_UNCERTAIN" in codes(auth.get(path).json())


@pytest.mark.parametrize("block", ["do_not_contact", "suppression", "sales"])
def test_hard_blocks_survive_shared_destination_and_alternative_email(auth, db, block):
    company = company_fixture(auth, db, "synthetic@shop.example")
    profile_fixture(
        db, company, sales_contact_status="PROHIBITED" if block == "sales" else "ALLOWED"
    )
    import_locations(
        auth,
        {"id": str(company.project_id)},
        [["Second shop", "https://shop.example", "", company.email, "City 2-2", ""]],
    )
    if block == "do_not_contact":
        company.do_not_contact = True
    elif block == "suppression":
        db.add(
            SuppressionEntry(
                project_id=company.project_id, domain=company.domain, reason="synthetic block"
            )
        )
    db.commit()
    result = evaluate(db, company)
    assert result["status"] == "BLOCKED"
    expected = {
        "do_not_contact": "DO_NOT_CONTACT",
        "suppression": "SUPPRESSED",
        "sales": "SALES_PROHIBITED",
    }[block]
    assert expected in codes(result)
    assert all(r["status"] == "BLOCKED" for r in result["destinations"])


def test_captcha_stale_mapping_and_nonprimary_are_distinct(auth, db):
    company = company_fixture(auth, db)
    profile = profile_fixture(
        db,
        company,
        captcha_type="CAPTCHA_RECAPTCHA",
        last_analyzed_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    db.add(
        FormProfileField(
            form_profile_id=profile.id,
            position=1,
            field_type="text",
            mapped_key="unknown",
            required=True,
            confidence=0,
        )
    )
    db.commit()
    secondary = profile_fixture(
        db, company, form_url="https://shop.example/partnership", is_primary=False
    )
    result = evaluate(db, company)
    rows = {r["destination"]: r for r in result["destinations"]}
    primary = rows[profile.form_url]
    assert primary["status"] == "HOLD"
    assert {"CAPTCHA", "FORM_ANALYSIS_STALE", "REQUIRED_FIELD_UNKNOWN"} <= codes(primary)
    assert "FORM_PROFILE_MISMATCH" in codes(rows[secondary.form_url])
    assert rows[secondary.form_url]["status"] != "READY"


def test_registered_contact_email_inventory_and_invalid_quality(auth, db):
    company = company_fixture(auth, db)
    contact = ContactPerson(
        company_id=company.id,
        name="Synthetic contact",
        email="person@example.com",
        source_url=company.website_url,
        verification_status="invalid",
    )
    db.add(contact)
    db.commit()
    result = evaluate(db, company)
    assert result["destinations"][0]["destination"] == contact.email
    assert "CONTACT_INVALID" in codes(result)
    contact.verification_status = "verified"
    db.commit()
    assert "EMAIL_UNVERIFIED" not in codes(evaluate(db, company))
    assert evaluate(db, company)["status"] == "REVIEW"


def test_missing_and_dangerous_destination_do_not_become_ready(auth, db):
    company = company_fixture(auth, db)
    assert evaluate(db, company)["status"] == "HOLD"
    company.contact_url = "http://localhost./contact"
    db.commit()
    result = evaluate(db, company)
    assert result["status"] == "BLOCKED" and "DESTINATION_INVALID" in codes(result)
    assert result["destinations"] == []


def test_project_reader_boundary_and_no_agent_cookie_reuse(auth, db, users):
    company = company_fixture(auth, db)
    project = db.get(Project, company.project_id)
    project.user_id = users[1].id
    db.commit()
    path = f"/api/companies/{company.id}/sendability"
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(path).status_code == 200
    assert auth.get(path, headers={"Authorization": "Bearer invalid-agent"}).status_code == 403
    assert auth.post(path, json={"confirmed": True}).status_code == 405


@pytest.mark.parametrize(
    "status,reason",
    [
        ("unknown", "DELIVERY_UNKNOWN"),
        ("submitted", "DUPLICATE_DESTINATION"),
        ("pending", "DUPLICATE_DESTINATION"),
    ],
)
def test_shared_destination_delivery_history_never_becomes_retryable(auth, db, status, reason):
    company = company_fixture(auth, db)
    profile_fixture(db, company)
    other_project = make_project(auth)
    import_locations(
        auth, other_project, [["Other synthetic", "https://other.example", "", "", "City 9-9", ""]]
    )
    other = db.scalar(select(Company).where(Company.project_id == UUID(other_project["id"])))
    draft = OutreachDraft(company_id=other.id, channel="form", body="Synthetic history, no POST")
    db.add(draft)
    db.flush()
    db.add(
        FormDelivery(
            company_id=other.id,
            draft_id=draft.id,
            form_url="https://shop.example/contact/",
            status=status,
        )
    )
    db.commit()
    result = evaluate(db, company)
    assert result["status"] == "BLOCKED" and reason in codes(result)
    serialized = str(result)
    assert str(other.id) not in serialized and str(other_project["id"]) not in serialized
    assert not result["execution_allowed"]


def test_evaluation_performs_only_selects_and_no_network(auth, db, monkeypatch):
    import httpx
    from sqlalchemy import event

    company = company_fixture(auth, db)
    profile_fixture(db, company)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    def forbidden(*args, **kwargs):
        raise AssertionError("Sendability must not perform external I/O")

    monkeypatch.setattr(httpx.Client, "request", forbidden)
    event.listen(db.connection(), "before_cursor_execute", capture)
    try:
        assert evaluate(db, company)["status"] == "REVIEW"
        assert statements and set(statements) == {"SELECT"}
        assert not db.new and not db.dirty and not db.deleted
    finally:
        event.remove(db.connection(), "before_cursor_execute", capture)
