import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (
    MasterCompany,
    MasterCompanySite,
    MasterFormReview,
    MasterObservation,
    Organization,
)
from app.services.master_data import (
    MasterDataError,
    apply_company_observations,
    get_or_create_master_company,
    get_or_create_site,
    normalize_company_identity,
    normalize_domain,
    normalize_email,
    normalize_host,
    normalize_phone,
    organization_form_suggestions,
    other_organization_form_suggestions,
    recipient_domain_key,
    record_observation,
    record_site_observations,
    reusable_form_structure,
    save_organization_form_review,
    store_form_structure,
    upsert_contact_page,
)


def test_normalizes_domain_email_phone_and_company_identity():
    assert normalize_host("HTTPS://WWW.例え.テスト.:443/path") == "www.xn--r8jz45g.xn--zckzah"
    assert normalize_domain("www.shop.example.co.jp") == "example.co.jp"
    assert normalize_email(" SALES@例え.テスト ") == "sales@xn--r8jz45g.xn--zckzah"
    assert normalize_phone("０３－１２３４－５６７８") == "0312345678"
    assert normalize_company_identity("株式会社 ＡＢＣ") == normalize_company_identity(
        "株式会社ABC"
    )


def test_recipient_domain_uses_host_for_shared_hosting_domain():
    assert recipient_domain_key("store-a.base.shop") == "store-a.base.shop"
    assert recipient_domain_key("www.example.co.jp") == "example.co.jp"


def test_master_company_only_deduplicates_by_corporate_number(db):
    first = get_or_create_master_company(db, "1234567890123")
    same_number = get_or_create_master_company(db, "1234567890123")
    separate_without_number = get_or_create_master_company(db)
    another_without_number = get_or_create_master_company(db)

    assert first.id == same_number.id
    assert separate_without_number.id != another_without_number.id
    assert first.name == ""
    assert first.status == "unverified"


def test_observation_policy_excludes_unknown_sources_and_google_places_content(db):
    company = get_or_create_master_company(db)
    with pytest.raises(MasterDataError):
        record_observation(
            db,
            field="name",
            value="CSV company",
            source="csv",
            source_url="upload.csv",
            master_company_id=company.id,
        )
    with pytest.raises(MasterDataError):
        record_observation(
            db,
            field="name",
            value="Places company",
            source="google_places",
            source_url="https://maps.example/",
            master_company_id=company.id,
        )

    record_observation(
        db,
        field="place_id",
        value="place-123",
        source="google_places",
        source_url="https://maps.example/",
        master_company_id=company.id,
    )
    assert company.name == ""


def test_master_company_values_are_derived_from_allowed_observations_only(db):
    company = get_or_create_master_company(db)
    record_observation(
        db,
        field="name",
        value="Official Site Co., Ltd.",
        source="site",
        source_url="https://official.example/about",
        master_company_id=company.id,
    )
    apply_company_observations(db, company)
    assert company.name == "Official Site Co., Ltd."


def test_site_values_are_recorded_with_source_and_csv_values_are_not_imported(db):
    existing = SimpleNamespace(
        source="serper",
        company_name="Old local value",
        corporate_number="",
        master_company_id=None,
        master_site_id=None,
        project_id=uuid.uuid4(),
    )
    observed = SimpleNamespace(
        company_name="Official Site Name",
        address="Tokyo",
        prefecture="東京都",
        city="千代田区",
        phone="03-1234-5678",
    )
    record_site_observations(db, existing, observed, "https://official.example/about")

    master = db.get(MasterCompany, existing.master_company_id)
    assert master.name == "Official Site Name"
    assert master.city == "千代田区"
    assert db.scalar(
        select(MasterObservation.id).where(
            MasterObservation.master_company_id == master.id,
            MasterObservation.field == "name",
            MasterObservation.source == "site",
            MasterObservation.source_url == "https://official.example/about",
        )
    )

    imported = SimpleNamespace(
        source="csv",
        company_name="CSV Only Name",
        corporate_number="",
        master_company_id=None,
        master_site_id=None,
        project_id=uuid.uuid4(),
    )
    record_site_observations(db, imported, observed, "https://csv.example/about")
    assert imported.master_company_id is None
    assert imported.master_site_id is None


def test_site_name_change_ends_old_unverified_company_site_link(db):
    company = SimpleNamespace(
        source="serper",
        company_name="Old Company",
        corporate_number="",
        master_company_id=None,
        master_site_id=None,
        project_id=uuid.uuid4(),
    )
    first_data = SimpleNamespace(
        company_name="Old Company",
        address="",
        prefecture="",
        city="",
        phone="",
    )
    record_site_observations(db, company, first_data, "https://formerly-old.example/")
    old_master_id = company.master_company_id
    old_site_id = company.master_site_id
    old_link = db.scalar(
        select(MasterCompanySite).where(
            MasterCompanySite.master_company_id == old_master_id,
            MasterCompanySite.master_site_id == old_site_id,
            MasterCompanySite.valid_until.is_(None),
        )
    )
    assert old_link is not None

    changed_data = SimpleNamespace(
        company_name="New Unrelated Corporation",
        address="",
        prefecture="",
        city="",
        phone="",
    )
    record_site_observations(db, company, changed_data, "https://formerly-old.example/")

    assert company.master_company_id != old_master_id
    assert old_link.valid_until is not None
    assert db.scalar(
        select(MasterCompanySite.id).where(
            MasterCompanySite.master_company_id == company.master_company_id,
            MasterCompanySite.master_site_id == old_site_id,
            MasterCompanySite.valid_until.is_(None),
        )
    )


def test_new_corporate_number_relinks_existing_company_to_canonical_master(db):
    company = SimpleNamespace(
        source="serper",
        company_name="Known Company",
        corporate_number="",
        master_company_id=None,
        master_site_id=None,
        project_id=uuid.uuid4(),
    )
    data = SimpleNamespace(
        company_name="Known Company",
        address="",
        prefecture="",
        city="",
        phone="",
    )
    website = "https://known-company.example/"
    record_site_observations(db, company, data, website)
    unverified_id = company.master_company_id
    company.corporate_number = "1234567890123"

    record_site_observations(db, company, data, website)

    assert company.master_company_id != unverified_id
    assert db.get(MasterCompany, company.master_company_id).corporate_number == "1234567890123"
    assert (
        db.scalar(
            select(MasterCompanySite.id).where(
                MasterCompanySite.master_company_id == unverified_id,
                MasterCompanySite.valid_until.is_(None),
            )
        )
        is None
    )


def test_contact_page_and_form_structure_cache_expire_and_match_analysis_version(db):
    site = get_or_create_site(db, "https://forms.example.co.jp", site_name="")
    page = upsert_contact_page(db, site, "https://forms.example.co.jp/contact")
    now = datetime.now(timezone.utc)
    stored = store_form_structure(
        db,
        page,
        form_index=0,
        fingerprint="a" * 64,
        fields=[
            {
                "name": "email",
                "selector": "#email",
                "label": "Email",
                "field_type": "email",
                "required": True,
                "options": [],
                "recommended_value": "person@example.com",
            }
        ],
        captcha_type="CAPTCHA_NONE",
        submission_kind="ordinary",
        confirmation_page=False,
        analysis_version="2.6",
        analyzed_at=now,
    )

    reusable = reusable_form_structure(
        db,
        contact_page_url=page.url,
        form_index=0,
        analysis_version="2.6",
        now=now + timedelta(days=89),
    )
    expired = reusable_form_structure(
        db,
        contact_page_url=page.url,
        form_index=0,
        analysis_version="2.6",
        now=now + timedelta(days=91),
    )
    outdated_version = reusable_form_structure(
        db,
        contact_page_url=page.url,
        form_index=0,
        analysis_version="2.7",
        now=now,
    )

    assert reusable.id == stored.id
    assert reusable.fields == [
        {
            "name": "email",
            "selector": "#email",
            "label": "Email",
            "field_type": "email",
            "required": True,
            "options": [],
        }
    ]
    assert expired is None
    assert outdated_version is None


def test_contact_page_url_cannot_be_rebound_to_different_master_site(db):
    first_site = get_or_create_site(db, "first.example")
    second_site = get_or_create_site(db, "second.example")
    upsert_contact_page(db, first_site, "https://first.example/contact")

    with pytest.raises(MasterDataError):
        upsert_contact_page(db, second_site, "https://first.example/contact")


def test_form_review_is_saved_per_organization_as_mapping_only(db, users):
    from types import SimpleNamespace

    first_org = Organization(name="First organization")
    second_org = Organization(name="Second organization")
    db.add_all((first_org, second_org))
    db.flush()
    profile = SimpleNamespace(
        form_url="https://shared.example/contact",
        form_index=0,
        fingerprint="c" * 64,
    )
    field = SimpleNamespace(
        name="email",
        selector="#email",
        field_type="email",
        mapped_key="sender_email",
        recommended_value="must-not-be-shared@example.com",
    )
    saved = save_organization_form_review(
        db,
        organization_id=first_org.id,
        profile=profile,
        fields=[field],
        fields_hash="d" * 64,
        confirmed_by_user_id=users[0].id,
    )

    assert saved.organization_id == first_org.id
    assert "recommended_value" not in saved.mapping_snapshot[0]
    assert db.get(MasterFormReview, saved.id) is not None
    suggestion = other_organization_form_suggestions(
        db, organization_id=second_org.id, profile=profile
    )
    assert suggestion == {("email", "#email", "email"): "sender_email"}
    assert (
        other_organization_form_suggestions(db, organization_id=first_org.id, profile=profile) == {}
    )


def test_form_review_mapping_is_reusable_only_within_same_org_and_exact_fingerprint(db, users):
    first_org = Organization(name="First organization")
    second_org = Organization(name="Second organization")
    db.add_all((first_org, second_org))
    db.flush()
    profile = SimpleNamespace(
        form_url="https://shared.example/contact",
        form_index=0,
        fingerprint="e" * 64,
    )
    field = SimpleNamespace(
        name="email",
        selector="#email",
        field_type="email",
        mapped_key="sender_email",
        recommended_value="never reused",
    )
    save_organization_form_review(
        db,
        organization_id=first_org.id,
        profile=profile,
        fields=[field],
        fields_hash="f" * 64,
        confirmed_by_user_id=users[0].id,
    )

    assert organization_form_suggestions(db, organization_id=first_org.id, profile=profile) == {
        ("email", "#email", "email"): "sender_email"
    }
    assert organization_form_suggestions(db, organization_id=second_org.id, profile=profile) == {}
    changed_structure = SimpleNamespace(
        form_url=profile.form_url,
        form_index=profile.form_index,
        fingerprint="a" * 64,
    )
    assert (
        organization_form_suggestions(db, organization_id=first_org.id, profile=changed_structure)
        == {}
    )


def test_company_table_starts_without_master_links(db, users):
    from app.models import Company, Project, TargetProfile

    profile = TargetProfile(user_id=users[0].id, profile_name="target")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=users[0].id,
        organization_id=None,
        project_name="project",
        target_profile_id=profile.id,
        sales_objective="test",
        region="",
    )
    db.add(project)
    db.flush()
    company = Company(
        project_id=project.id,
        company_name="Existing record",
        source="csv",
    )
    db.add(company)
    db.flush()

    assert company.master_company_id is None
    assert company.master_site_id is None


def test_analyzer_reuses_fresh_master_structure_without_fetching(db, users, monkeypatch):
    from app.models import Company, Project, TargetProfile
    from app.services.form_intelligence import analyzer

    profile = TargetProfile(user_id=users[0].id, profile_name="target")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=users[0].id,
        organization_id=None,
        project_name="project",
        target_profile_id=profile.id,
        sales_objective="test",
        region="",
    )
    db.add(project)
    db.flush()
    contact_url = "https://reuse.example.co.jp/contact"
    company = Company(
        project_id=project.id,
        company_name="Example Co.",
        source="serper",
        website_url="https://reuse.example.co.jp/",
        contact_url=contact_url,
    )
    db.add(company)
    db.flush()
    site = get_or_create_site(db, company.website_url)
    page = upsert_contact_page(db, site, contact_url)
    store_form_structure(
        db,
        page,
        form_index=0,
        fingerprint="b" * 64,
        fields=[
            {
                "name": "email",
                "selector": "#email",
                "label": "Email",
                "field_type": "email",
                "required": True,
                "options": [],
            }
        ],
        captcha_type="CAPTCHA_NONE",
        submission_kind="",
        confirmation_page=False,
        analysis_version=analyzer.ANALYSIS_VERSION,
    )

    class NoNetworkFetcher:
        def __init__(self):
            raise AssertionError("cached analysis must not fetch a website")

    monkeypatch.setattr(analyzer, "SafeFetcher", NoNetworkFetcher)
    result = analyzer.analyze_company_forms(db, company)

    assert len(result) == 1
    assert result[0].fingerprint == "b" * 64
    assert result[0].analysis_provider == "master_cache"
    assert result[0].form_status == "REVIEW_REQUIRED"


def test_site_backfill_commits_chunks_and_skips_csv_url_sources(db, users):
    from app.models import Company, OperationJob, Project, TargetProfile
    from app.services.master_data import backfill_project_sites

    profile = TargetProfile(user_id=users[0].id, profile_name="target")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=users[0].id,
        organization_id=None,
        project_name="project",
        target_profile_id=profile.id,
        sales_objective="test",
        region="",
    )
    db.add(project)
    db.flush()
    companies = [
        Company(
            project_id=project.id,
            company_name=f"Company {index}",
            source="serper",
            website_url=f"https://company-{index}.example.co.jp/",
        )
        for index in range(501)
    ]
    companies.extend(
        [
            Company(
                project_id=project.id,
                company_name="CSV record",
                source="csv",
                website_url="https://csv.example.co.jp/",
            ),
            Company(
                project_id=project.id,
                company_name="URL record",
                source="url",
                website_url="https://url.example.co.jp/",
            ),
        ]
    )
    db.add_all(companies)
    worker_id = uuid.uuid4()
    job = OperationJob(
        project_id=project.id,
        operation_type="master_site_backfill",
        status="running",
        worker_id=worker_id,
        total_count=501,
    )
    db.add(job)
    db.flush()
    project_id = project.id
    job_id = job.id

    backfill_project_sites(db, job, worker_id, lambda *_: False)

    db.expire_all()
    assert db.scalar(
        select(Company.id)
        .where(
            Company.project_id == project_id,
            Company.source == "serper",
            Company.master_site_id.is_not(None),
        )
        .limit(1)
    )
    assert (
        db.scalar(
            select(Company.id)
            .where(
                Company.project_id == project_id,
                Company.source.in_(("csv", "url")),
                Company.master_site_id.is_not(None),
            )
            .limit(1)
        )
        is None
    )
    persisted_job = db.get(OperationJob, job_id)
    assert persisted_job.processed_count == 501
    assert persisted_job.success_count == 501
