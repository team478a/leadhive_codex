from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import (
    Company,
    FormDelivery,
    FormDispatchLimits,
    Organization,
    OrganizationMember,
    OutreachDraft,
    Project,
    TargetProfile,
    User,
)
from app.services.recipient_cooldown import (
    at_limit,
    count_usage,
    matching_company_ids,
    reserve_slot,
    target_keys,
)
from app.services.sendability import evaluate
from tests.test_sendability import company_fixture


def test_legacy_form_submissions_count_toward_cross_project_cooldown(auth, db):
    limits = db.get(FormDispatchLimits, 1)
    limits.recipient_cooldown_limit = 2
    company = company_fixture(auth, db)
    company.domain = "shop.example"
    company.contact_url = "https://shop.example/contact"
    now = datetime.now(timezone.utc)
    for index in range(2):
        draft = OutreachDraft(
            company_id=company.id,
            channel="form",
            body=f"synthetic message {index}",
        )
        db.add(draft)
        db.flush()
        db.add(
            FormDelivery(
                draft_id=draft.id,
                company_id=company.id,
                form_url=f"https://shop.example/contact-{index}",
                delivery_method="direct",
                status="submitted",
                submitted_at=now,
            )
        )
    db.flush()

    keys, corporate_number = target_keys(db, company)
    assert keys == ("shop.example",)
    assert corporate_number is None
    assert at_limit(db, company, now)
    assessment = evaluate(db, company)
    assert any(
        reason["code"] == "RECIPIENT_COOLDOWN"
        for destination in assessment["destinations"]
        for reason in destination["reasons"]
    )
    allowed, _, _, used = reserve_slot(db, company, now)
    assert not allowed
    assert used == 2


def test_corporate_number_is_preserved_as_a_second_recipient_key(auth, db):
    company = company_fixture(auth, db)
    company.corporate_number = "1234567890123"
    other_company = Company(
        project_id=company.project_id,
        company_name="Synthetic second company",
        domain="other.example",
        website_url="https://other.example",
        corporate_number=company.corporate_number,
        source="csv",
    )
    db.add(other_company)
    db.flush()
    draft = OutreachDraft(company_id=other_company.id, channel="form", body="synthetic")
    db.add(draft)
    db.flush()
    db.add(
        FormDelivery(
            draft_id=draft.id,
            company_id=other_company.id,
            form_url="https://other.example/contact",
            delivery_method="direct",
            status="unknown",
        )
    )
    db.flush()

    keys, corporate_number = target_keys(db, company)
    assert keys == ("shop.example",)
    assert corporate_number == "1234567890123"
    company_ids = matching_company_ids(db, keys, corporate_number)
    assert other_company.id in company_ids
    assert count_usage(db, keys, corporate_number, company_ids) == 1


def test_pre_post_failure_is_not_counted_but_unknown_is(auth, db):
    limits = db.get(FormDispatchLimits, 1)
    limits.recipient_cooldown_limit = 1
    company = company_fixture(auth, db)
    company.domain = "shop.example"
    failed_draft = OutreachDraft(company_id=company.id, channel="form", body="synthetic")
    unknown_draft = OutreachDraft(company_id=company.id, channel="form", body="synthetic")
    db.add_all([failed_draft, unknown_draft])
    db.flush()
    db.add_all(
        [
            FormDelivery(
                draft_id=failed_draft.id,
                company_id=company.id,
                form_url="https://shop.example/failed",
                delivery_method="direct",
                status="failed",
            ),
            FormDelivery(
                draft_id=unknown_draft.id,
                company_id=company.id,
                form_url="https://shop.example/unknown",
                delivery_method="direct",
                status="unknown",
            ),
        ]
    )
    db.flush()

    allowed, _keys, _corporate_number, used = reserve_slot(db, company)
    assert not allowed
    assert used == 1


@pytest.mark.parametrize("same_recipient", [True, False])
def test_concurrent_reservations_do_not_exceed_limit(same_recipient):
    suffix = uuid4().hex
    user_id = uuid4()
    profile_id = uuid4()
    company_ids = [uuid4(), uuid4()]
    with SessionLocal() as session:
        user = User(id=user_id, email=f"cooldown-{suffix}@example.test", password_hash="synthetic")
        profile = TargetProfile(
            id=profile_id,
            user_id=user_id,
            profile_name=f"Cooldown {suffix}",
            is_system=False,
        )
        session.add(user)
        session.flush()
        session.add(profile)
        session.flush()
        project = Project(
            user_id=user_id,
            target_profile_id=profile_id,
            project_name=f"Cooldown {suffix}",
            sales_objective="synthetic test",
            region="synthetic",
        )
        session.add(project)
        session.flush()
        corporate_number = "1234567890123" if not same_recipient else ""
        companies = [
            Company(
                id=company_ids[index],
                project_id=project.id,
                company_name=f"Synthetic {suffix} {index}",
                domain=f"site-{index}-{suffix}.example.test",
                website_url=f"https://site-{index}-{suffix}.example.test",
                corporate_number=corporate_number,
                source="csv",
            )
            for index in range(2)
        ]
        session.add_all(companies)
        limits = session.get(FormDispatchLimits, 1)
        original_limit = limits.recipient_cooldown_limit
        limits.recipient_cooldown_limit = 1
        session.commit()
        if same_recipient:
            company_ids[1] = company_ids[0]

    ready_to_commit = Event()
    allow_first_commit = Event()
    second_started = Event()

    def try_reservation(company_id, hold):
        with SessionLocal() as session:
            company = session.get(Company, company_id)
            allowed, keys, corporate, used = reserve_slot(session, company)
            if hold:
                ready_to_commit.set()
                assert allow_first_commit.wait(5)
            if allowed:
                draft = OutreachDraft(
                    company_id=company.id,
                    channel="form",
                    body="synthetic concurrent reservation",
                )
                session.add(draft)
                session.flush()
                session.add(
                    FormDelivery(
                        draft_id=draft.id,
                        company_id=company.id,
                        form_url=f"https://{company.domain}/contact",
                        recipient_key=keys[0] if keys else None,
                        corporate_number=corporate,
                        delivery_method="direct",
                        status="unknown",
                    )
                )
            session.commit()
            return allowed, used

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(try_reservation, company_ids[0], True)
            assert ready_to_commit.wait(5)

            def start_second():
                second_started.set()
                return try_reservation(company_ids[1], False)

            second = executor.submit(start_second)
            assert second_started.wait(5)
            sleep(0.1)
            allow_first_commit.set()
            first_result, second_result = first.result(timeout=10), second.result(timeout=10)
        assert sum(int(result[0]) for result in (first_result, second_result)) == 1
        assert second_result[1] == 1
    finally:
        with SessionLocal() as session:
            project = session.scalar(select(Project).where(Project.user_id == user_id))
            if project:
                organization_id = project.organization_id
                session.delete(project)
                session.flush()
                if organization_id:
                    session.execute(
                        delete(OrganizationMember).where(
                            OrganizationMember.organization_id == organization_id
                        )
                    )
                    organization = session.get(Organization, organization_id)
                    if organization:
                        session.delete(organization)
            profile = session.get(TargetProfile, profile_id)
            if profile:
                session.delete(profile)
            user = session.get(User, user_id)
            if user:
                session.delete(user)
            limits = session.get(FormDispatchLimits, 1)
            if limits:
                limits.recipient_cooldown_limit = original_limit
            session.commit()
