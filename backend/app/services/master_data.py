import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlsplit

import tldextract
from sqlalchemy import case, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    Company,
    MasterCompany,
    MasterCompanySite,
    MasterContactPage,
    MasterFormReview,
    MasterFormStructure,
    MasterObservation,
    MasterSite,
    OperationJob,
    Project,
)

ANALYSIS_REUSE_DAYS = 90
ALLOWED_OBSERVATION_SOURCES = frozenset({"site", "nta", "gbizinfo", "form_first", "google_places"})
MASTER_FIELDS = frozenset(
    {
        "name",
        "prefecture",
        "city",
        "address",
        "phone",
        "corporate_number",
        "status",
        "place_id",
        "website_url",
    }
)
GOOGLE_PLACES_FIELDS = frozenset({"place_id"})
COMMON_HOSTED_DOMAINS = frozenset(
    {
        "amebaownd.com",
        "blogspot.com",
        "base.shop",
        "blog.jp",
        "fc2.com",
        "jimdo.com",
        "myshopify.com",
        "shop-pro.jp",
        "square.site",
        "stores.jp",
        "wixsite.com",
        "wordpress.com",
    }
)
_extract = tldextract.TLDExtract(suffix_list_urls=())


class MasterDataError(ValueError):
    pass


def normalize_host(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = (parsed.hostname or "").rstrip(".").casefold()
    if not host:
        return ""
    try:
        return ".".join(label.encode("idna").decode("ascii") for label in host.split("."))
    except UnicodeError as exc:
        raise MasterDataError("invalid internationalized domain") from exc


def normalize_domain(value: str) -> str:
    host = normalize_host(value)
    if host.startswith("www."):
        host = host[4:]
    extracted = _extract(host)
    return (
        f"{extracted.domain}.{extracted.suffix}" if extracted.domain and extracted.suffix else host
    )


def normalize_email(value: str) -> str:
    local, separator, domain = unicodedata.normalize("NFKC", value or "").strip().rpartition("@")
    if not separator or not local or not domain:
        return ""
    return f"{local.casefold()}@{normalize_host(domain)}"


def normalize_phone(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    prefix = "+" if normalized.startswith("+") else ""
    digits = "".join(char for char in normalized if char.isdigit())
    return prefix + digits


def normalize_company_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[\W_]+", "", normalized)


def recipient_domain_key(value: str) -> str:
    host = normalize_host(value)
    domain = normalize_domain(host)
    return host if domain in COMMON_HOSTED_DOMAINS else domain


def get_or_create_site(
    db: Session,
    url_or_host: str,
    *,
    site_name: str = "",
    now: datetime | None = None,
) -> MasterSite:
    host = normalize_host(url_or_host)
    if not host:
        raise MasterDataError("site URL must include a valid host")
    timestamp = now or datetime.now(timezone.utc)
    domain = normalize_domain(host)
    stmt = insert(MasterSite).values(
        id=uuid.uuid4(),
        host=host,
        registrable_domain=domain,
        first_seen_at=timestamp,
        last_seen_at=timestamp,
        last_site_name=(site_name or "")[:500],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[MasterSite.host],
        set_={
            "last_seen_at": timestamp,
            "last_site_name": (site_name or "")[:500] or MasterSite.last_site_name,
            "registrable_domain": domain,
        },
    ).returning(MasterSite.id)
    site_id = db.scalar(stmt)
    db.flush()
    return db.get(MasterSite, site_id)


def get_or_create_master_company(db: Session, corporate_number: str | None = None) -> MasterCompany:
    number = re.sub(r"\D", "", corporate_number or "")
    if number and len(number) != 13:
        raise MasterDataError("corporate number must contain 13 digits")
    if number:
        stmt = (
            insert(MasterCompany)
            .values(
                id=uuid.uuid4(),
                corporate_number=number,
                name="",
                prefecture="",
                city="",
                status="unverified",
            )
            .on_conflict_do_nothing(
                index_elements=[MasterCompany.corporate_number],
                index_where=text("corporate_number IS NOT NULL"),
            )
            .returning(MasterCompany.id)
        )
        company_id = db.scalar(stmt)
        if company_id is not None:
            db.flush()
            return db.get(MasterCompany, company_id)
        return db.scalar(select(MasterCompany).where(MasterCompany.corporate_number == number))
    company = MasterCompany(corporate_number=number or None, status="unverified")
    db.add(company)
    db.flush()
    return company


def link_company_site(
    db: Session,
    company: MasterCompany,
    site: MasterSite,
    *,
    relation: str = "unknown",
    evidence: dict | None = None,
    observed_at: datetime | None = None,
) -> MasterCompanySite:
    if relation not in {"primary", "brand", "store", "unknown"}:
        raise MasterDataError("invalid company-site relation")
    observed = observed_at or datetime.now(timezone.utc)
    existing = db.scalar(
        select(MasterCompanySite).where(
            MasterCompanySite.master_company_id == company.id,
            MasterCompanySite.master_site_id == site.id,
            MasterCompanySite.valid_until.is_(None),
        )
    )
    if existing:
        existing.relation = relation
        existing.evidence = evidence or existing.evidence
        existing.observed_at = observed
        db.flush()
        return existing
    link = MasterCompanySite(
        master_company_id=company.id,
        master_site_id=site.id,
        relation=relation,
        evidence=evidence or {},
        observed_at=observed,
    )
    db.add(link)
    db.flush()
    return link


def record_observation(
    db: Session,
    *,
    field: str,
    value,
    source: str,
    source_url: str,
    master_company_id: uuid.UUID | None = None,
    master_site_id: uuid.UUID | None = None,
    observed_by_org_id: uuid.UUID | None = None,
    observed_at: datetime | None = None,
) -> MasterObservation:
    if source not in ALLOWED_OBSERVATION_SOURCES:
        raise MasterDataError("observation source is not allowed")
    if field not in MASTER_FIELDS:
        raise MasterDataError("observation field is not allowed")
    if source == "google_places" and field not in GOOGLE_PLACES_FIELDS:
        raise MasterDataError("Google Places observations may only store place_id")
    if (master_company_id is None) == (master_site_id is None):
        raise MasterDataError("exactly one master subject is required")
    if not source_url.strip():
        raise MasterDataError("source URL is required")
    observation = MasterObservation(
        master_company_id=master_company_id,
        master_site_id=master_site_id,
        field=field,
        value=value,
        source=source,
        source_url=source_url.strip(),
        observed_by_org_id=observed_by_org_id,
        observed_at=observed_at or datetime.now(timezone.utc),
    )
    db.add(observation)
    db.flush()
    return observation


def apply_company_observations(db: Session, company: MasterCompany) -> None:
    observations = db.scalars(
        select(MasterObservation)
        .where(
            MasterObservation.master_company_id == company.id,
            MasterObservation.source.in_(("site", "nta", "gbizinfo", "form_first")),
            MasterObservation.field.in_(
                ("name", "prefecture", "city", "corporate_number", "status")
            ),
        )
        .order_by(MasterObservation.observed_at, MasterObservation.id)
    ).all()
    latest = {}
    for item in observations:
        latest[item.field] = item.value
    for field in ("name", "prefecture", "city", "status"):
        value = latest.get(field)
        if isinstance(value, str) and value.strip():
            setattr(company, field, value.strip())
    number = latest.get("corporate_number")
    if isinstance(number, str) and re.fullmatch(r"\d{13}", number):
        company.corporate_number = number
    db.flush()


def record_site_observations(db: Session, company: Company, data, source_url: str) -> None:
    if company.source in {"csv", "url"} or not source_url.strip():
        return
    previous_site_id = company.master_site_id
    previous_master_company = (
        db.get(MasterCompany, company.master_company_id) if company.master_company_id else None
    )
    previous_site_name = ""
    if previous_site_id:
        previous_site = db.get(MasterSite, previous_site_id)
        previous_site_name = previous_site.last_site_name if previous_site else ""
    site = get_or_create_site(db, source_url, site_name=data.company_name or "")
    company.master_site_id = site.id
    master_company = previous_master_company
    corporate_number = re.sub(r"\D", "", company.corporate_number or "")
    if len(corporate_number) != 13:
        corporate_number = ""
    observed_name = (data.company_name or "").strip()
    name_changed = bool(
        previous_site_name
        and observed_name
        and SequenceMatcher(
            None,
            normalize_company_identity(previous_site_name),
            normalize_company_identity(observed_name),
        ).ratio()
        < 0.7
    )
    identity_changed = (
        bool(
            previous_site_id
            and previous_site_id != site.id
            and previous_master_company
            and not previous_master_company.corporate_number
        )
        or bool(
            name_changed
            and previous_master_company
            and not previous_master_company.corporate_number
        )
        or bool(
            corporate_number
            and previous_master_company
            and previous_master_company.corporate_number != corporate_number
        )
    )
    if identity_changed:
        db.execute(
            update(MasterCompanySite)
            .where(
                MasterCompanySite.master_company_id == previous_master_company.id,
                MasterCompanySite.master_site_id == (previous_site_id or site.id),
                MasterCompanySite.valid_until.is_(None),
            )
            .values(valid_until=datetime.now(timezone.utc))
        )
        master_company = None
    if master_company is None:
        master_company = get_or_create_master_company(db, corporate_number or None)
        company.master_company_id = master_company.id
    project = db.get(Project, company.project_id)
    link_company_site(
        db,
        master_company,
        site,
        relation="primary",
        evidence={"source": "site", "source_url": source_url},
    )
    values = {
        "name": data.company_name,
        "address": data.address,
        "prefecture": data.prefecture,
        "city": data.city,
        "phone": data.phone,
        "website_url": source_url,
    }
    for field, value in values.items():
        if isinstance(value, str) and value.strip():
            record_observation(
                db,
                field=field,
                value=value.strip(),
                source="site",
                source_url=source_url,
                master_company_id=master_company.id,
                observed_by_org_id=project.organization_id if project else None,
            )
    apply_company_observations(db, master_company)


def upsert_contact_page(db: Session, site: MasterSite, url: str) -> MasterContactPage:
    normalized = (url or "").strip()
    if not normalized.startswith(("http://", "https://")):
        raise MasterDataError("contact page URL must be absolute HTTP(S)")
    page = db.scalar(select(MasterContactPage).where(MasterContactPage.url == normalized))
    if page:
        if page.master_site_id != site.id:
            raise MasterDataError("contact page URL is already associated with another site")
        return page
    page = MasterContactPage(master_site_id=site.id, url=normalized)
    db.add(page)
    db.flush()
    return page


def store_form_structure(
    db: Session,
    page: MasterContactPage,
    *,
    form_index: int,
    fingerprint: str,
    fields: list[dict],
    captcha_type: str,
    submission_kind: str,
    confirmation_page: bool | None,
    analysis_version: str,
    analyzed_at: datetime | None = None,
) -> MasterFormStructure:
    if form_index < 0 or not fingerprint:
        raise MasterDataError("form index and fingerprint are required")
    structural_fields = [
        {
            key: field[key]
            for key in ("name", "selector", "label", "field_type", "required", "options")
            if key in field
        }
        for field in fields
    ]
    row = db.scalar(
        select(MasterFormStructure).where(
            MasterFormStructure.master_contact_page_id == page.id,
            MasterFormStructure.form_index == form_index,
            MasterFormStructure.fingerprint == fingerprint,
        )
    )
    timestamp = analyzed_at or datetime.now(timezone.utc)
    if row is None:
        row = MasterFormStructure(
            master_contact_page_id=page.id,
            form_index=form_index,
            fingerprint=fingerprint,
        )
        db.add(row)
    row.fields = structural_fields
    row.captcha_type = captcha_type
    row.submission_kind = submission_kind
    row.confirmation_page = confirmation_page
    row.analysis_version = analysis_version
    row.analyzed_at = timestamp
    db.flush()
    return row


def save_organization_form_review(
    db: Session,
    *,
    organization_id: uuid.UUID,
    profile,
    fields: list,
    fields_hash: str,
    confirmed_by_user_id: uuid.UUID,
) -> MasterFormReview:
    page_hash = hashlib.sha256(profile.form_url.encode("utf-8")).hexdigest()
    snapshot = [
        {
            "name": field.name,
            "selector": field.selector,
            "field_type": field.field_type,
            "mapped_key": field.mapped_key,
        }
        for field in fields
    ]
    now = datetime.now(timezone.utc)
    stmt = insert(MasterFormReview).values(
        id=uuid.uuid4(),
        organization_id=organization_id,
        contact_page_url=profile.form_url,
        contact_page_hash=page_hash,
        form_index=profile.form_index,
        fingerprint=profile.fingerprint,
        fields_hash=fields_hash,
        mapping_snapshot=snapshot,
        confirmed_no_sales_prohibition=True,
        confirmed_by_user_id=confirmed_by_user_id,
        created_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_master_form_review_org_page_form",
        set_={
            "contact_page_url": profile.form_url,
            "fields_hash": fields_hash,
            "mapping_snapshot": snapshot,
            "confirmed_no_sales_prohibition": True,
            "confirmed_by_user_id": confirmed_by_user_id,
            "created_at": now,
        },
    ).returning(MasterFormReview.id)
    review_id = db.scalar(stmt)
    db.flush()
    return db.get(MasterFormReview, review_id)


def form_review_suggestion_sets(
    db: Session,
    *,
    organization_id: uuid.UUID,
    profile,
) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str, str], str]]:
    return _organization_form_suggestions(db, organization_id=organization_id, profile=profile)


def organization_form_suggestions(
    db: Session,
    *,
    organization_id: uuid.UUID,
    profile,
) -> dict[tuple[str, str, str], str]:
    return _organization_form_suggestions(db, organization_id=organization_id, profile=profile)[0]


def other_organization_form_suggestions(
    db: Session,
    *,
    organization_id: uuid.UUID,
    profile,
) -> dict[tuple[str, str, str], str]:
    return _organization_form_suggestions(db, organization_id=organization_id, profile=profile)[1]


def _organization_form_suggestions(
    db: Session,
    *,
    organization_id: uuid.UUID,
    profile,
) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str, str], str]]:
    page_hash = hashlib.sha256(profile.form_url.encode("utf-8")).hexdigest()
    reviews = db.scalars(
        select(MasterFormReview)
        .where(
            MasterFormReview.contact_page_hash == page_hash,
            MasterFormReview.form_index == profile.form_index,
            MasterFormReview.fingerprint == profile.fingerprint,
            MasterFormReview.confirmed_no_sales_prohibition.is_(True),
        )
        .order_by(
            case((MasterFormReview.organization_id == organization_id, 0), else_=1),
            MasterFormReview.created_at.desc(),
            MasterFormReview.id.desc(),
        )
        .limit(2)
    ).all()
    suggestions: list[dict[tuple[str, str, str], str]] = [{}, {}]
    other_selected = False
    for review in reviews:
        is_same_org = review.organization_id == organization_id
        if not is_same_org and other_selected:
            continue
        index = 0 if is_same_org else 1
        if index == 1:
            other_selected = True
        suggestions[index] = {
            (item.get("name", ""), item.get("selector", ""), item.get("field_type", "")): item[
                "mapped_key"
            ]
            for item in review.mapping_snapshot
            if isinstance(item, dict) and item.get("mapped_key")
        }
    return suggestions[0], suggestions[1]


def reusable_form_structure(
    db: Session,
    *,
    contact_page_url: str,
    form_index: int,
    analysis_version: str,
    now: datetime | None = None,
) -> MasterFormStructure | None:
    current = now or datetime.now(timezone.utc)
    return db.scalar(
        select(MasterFormStructure)
        .join(MasterContactPage)
        .where(
            MasterContactPage.url == contact_page_url,
            MasterFormStructure.form_index == form_index,
            MasterFormStructure.analysis_version == analysis_version,
            MasterFormStructure.analyzed_at >= current - timedelta(days=ANALYSIS_REUSE_DAYS),
        )
        .order_by(MasterFormStructure.analyzed_at.desc())
        .limit(1)
    )


def attach_site_to_project_company(db: Session, company: Company, site: MasterSite) -> None:
    if company.source in {"csv", "url"}:
        return
    company.master_site_id = site.id
    db.flush()


def backfill_project_sites(db: Session, job: OperationJob, worker_id, stop_requested) -> None:
    job_id = job.id
    project_id = job.project_id
    last_company_id = None
    while True:
        current_job = db.get(OperationJob, job_id)
        if current_job is None or stop_requested(db, current_job, worker_id):
            return
        statement = select(Company.id, Company.website_url).where(
            Company.project_id == project_id,
            Company.record_type == "company",
            Company.source.notin_(("csv", "url")),
            Company.master_site_id.is_(None),
            Company.website_url.is_not(None),
        )
        if last_company_id is not None:
            statement = statement.where(Company.id > last_company_id)
        rows = db.execute(statement.order_by(Company.id).limit(500)).all()
        if not rows:
            return
        succeeded = failed = 0
        for company_id, website_url in rows:
            last_company_id = company_id
            try:
                site = get_or_create_site(db, website_url)
                db.execute(
                    update(Company)
                    .where(Company.id == company_id, Company.master_site_id.is_(None))
                    .values(master_site_id=site.id)
                )
                succeeded += 1
            except MasterDataError:
                failed += 1
        current_job = db.get(OperationJob, job_id)
        current_job.total_count = max(
            current_job.total_count, current_job.processed_count + len(rows)
        )
        current_job.processed_count += len(rows)
        current_job.success_count += succeeded
        current_job.failed_count += failed
        current_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.commit()
        db.expunge_all()
