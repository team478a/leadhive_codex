"""Persistence and deduplication for collection jobs."""

import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CollectionJob, Company, Project, SuppressionEntry
from app.services.collection import Candidate, canonicalize_url
from app.services.collection_discovery import classify_candidate, mark_discovery
from app.services.external_presence import capture_candidate
from app.services.lead_enrichment import observe_candidate
from app.services.location_identity import location_key
from app.services.scraper import is_aggregator_domain
from app.services.suppression import active_suppression_scope_condition

logger = logging.getLogger("leadhive")
PUBLIC_HOST_SUFFIXES = (".lg.jp", ".go.jp", ".ed.jp", ".ac.jp")
PUBLIC_HOST_PREFIXES = ("city.", "pref.", "town.", "vill.")
DEFINITE_ARTICLE_TITLE = re.compile(
    r"(?:[0-9０-９]+年版|年度|調べてみた|がスタート|開催|募集|とは)|"
    r"^(?:»|・|【)|[｜|]\s*[^｜|]*(?:都|道|府|県|市|区|町|村)$"
)


def start_job(
    db: Session,
    project_id: UUID,
    source: str,
    keyword: str,
    region: str,
    operation_job_id: UUID | None = None,
    search_schedule_id: UUID | None = None,
) -> CollectionJob:
    job = CollectionJob(
        project_id=project_id,
        operation_job_id=operation_job_id,
        search_schedule_id=search_schedule_id,
        source=source,
        keyword=keyword,
        region=region,
        status="running",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info("collection job start: id=%s source=%s", job.id, source)
    return job


def duplicate_company(db: Session, project_id: UUID, candidate: Candidate) -> Company | None:
    if candidate.record_type == "location":
        key = location_key(
            candidate.company_name,
            candidate.address,
            candidate.reference_url or candidate.website_url or "",
        )
        return db.scalar(
            select(Company)
            .where(
                Company.project_id == project_id,
                Company.record_type == "location",
                Company.location_key == key,
            )
            .limit(1)
        )
    conditions = []
    if candidate.website_url:
        _, domain = canonicalize_url(candidate.website_url)
        conditions.extend([Company.domain == domain, Company.website_url == candidate.website_url])
    if candidate.address:
        conditions.append(
            (Company.company_name == candidate.company_name)
            & (Company.address == candidate.address)
        )
    return (
        db.scalar(
            select(Company)
            .where(
                Company.project_id == project_id, Company.record_type == "company", or_(*conditions)
            )
            .limit(1)
        )
        if conditions
        else None
    )


def is_duplicate(db: Session, project_id: UUID, candidate: Candidate) -> bool:
    return duplicate_company(db, project_id, candidate) is not None


def is_suppressed(db: Session, project_id: UUID, candidate: Candidate) -> bool:
    project = db.get(Project, project_id)
    if project is None:
        return False
    conditions = []
    for url in (candidate.website_url, candidate.reference_url):
        if not url:
            continue
        _, domain = canonicalize_url(url)
        conditions.append((SuppressionEntry.domain != "") & (SuppressionEntry.domain == domain))
    if candidate.email:
        conditions.append(
            (SuppressionEntry.email != "")
            & (func.lower(SuppressionEntry.email) == candidate.email.lower())
        )
    if candidate.phone:
        conditions.append(
            (SuppressionEntry.phone != "") & (SuppressionEntry.phone == candidate.phone)
        )
    return (
        bool(conditions)
        and db.scalar(
            select(SuppressionEntry.id)
            .where(
                active_suppression_scope_condition(project_id, project.organization_id),
                or_(*conditions),
            )
            .limit(1)
        )
        is not None
    )


def definite_non_company_reason(job: CollectionJob, candidate: Candidate) -> str:
    if candidate.record_type != "company" or not candidate.website_url:
        return ""
    try:
        _, host = canonicalize_url(candidate.website_url)
    except (ValueError, UnicodeError):
        return ""
    if host.endswith(PUBLIC_HOST_SUFFIXES) or host.startswith(PUBLIC_HOST_PREFIXES):
        return "PUBLIC_SECTOR_DOMAIN"
    if job.source == "serper" and DEFINITE_ARTICLE_TITLE.search(candidate.company_name.strip()):
        return "ARTICLE_STYLE_TITLE"
    return ""


def save_candidates(
    db: Session,
    job: CollectionJob,
    candidates: list[Candidate],
    source_keyword: str = "",
    input_errors: int | list[dict[str, object]] = 0,
    *,
    before_commit: Callable[[], None] | None = None,
) -> CollectionJob:
    collection_job_id = job.id
    saved_company_ids: list[UUID] = []
    error_details = input_errors if isinstance(input_errors, list) else []
    error_count = len(input_errors) if isinstance(input_errors, list) else input_errors
    job.found_count = len(candidates) + error_count
    job.error_count = error_count
    job.import_errors = error_details
    # Serialize same-project ingestion without holding this lock across network calls.
    # Same-project ingestion remains serialized; FK key-share locks stay compatible.
    db.scalar(
        select(Project.id).where(Project.id == job.project_id).with_for_update(key_share=True)
    )
    from app.services.source_exclusions import domain_key, domains

    remembered_sources = domains(db, job.project_id)
    for candidate in candidates:
        capture_candidate(db, job, candidate)
        exclusion_reason = definite_non_company_reason(job, candidate)
        if exclusion_reason:
            job.excluded_count += 1
            mark_discovery(db, job, candidate, "NON_COMPANY_SOURCE")
            continue
        if candidate.site_discovery.get("kind") == "REFERENCE_DOCUMENT":
            job.excluded_count += 1
            mark_discovery(db, job, candidate, "NON_COMPANY_SOURCE")
            continue
        if candidate.website_url and domain_key(candidate.website_url) in remembered_sources:
            job.excluded_count += 1
            mark_discovery(db, job, candidate, "NON_COMPANY_SOURCE")
            continue
        if job.source == "serper" and candidate.website_url:
            kind, reason = classify_candidate(candidate)
            if (
                kind in {"SOCIAL", "PORTAL_DIRECTORY", "OTHER"}
                or (kind == "JOB_PR" and reason == "EXTERNAL_PLATFORM")
                or (kind == "ARTICLE" and reason == "AGGREGATION_TITLE")
            ):
                job.excluded_count += 1
                mark_discovery(db, job, candidate, "NON_COMPANY_SOURCE")
                continue
        if candidate.website_url:
            _, candidate_domain = canonicalize_url(candidate.website_url)
            if is_aggregator_domain(candidate_domain):
                if candidate.record_type == "location":
                    candidate.reference_url = candidate.reference_url or candidate.website_url
                    candidate.website_url = None
                else:
                    job.excluded_count += 1
                    mark_discovery(db, job, candidate, "AGGREGATOR_EXCLUDED")
                    continue
        if is_suppressed(db, job.project_id, candidate):
            job.duplicate_count += 1
            mark_discovery(db, job, candidate, "SUPPRESSED")
            continue
        duplicate = duplicate_company(db, job.project_id, candidate)
        if duplicate:
            db.refresh(duplicate, with_for_update=True)
            observe_candidate(db, job, duplicate, candidate)
            capture_candidate(db, job, candidate, duplicate)
            job.duplicate_count += 1
            mark_discovery(db, job, candidate, "DUPLICATE", duplicate)
            continue
        domain = None
        if candidate.website_url:
            candidate.website_url, domain = canonicalize_url(candidate.website_url)
        company = Company(
            project_id=job.project_id,
            company_name=candidate.company_name,
            record_type=candidate.record_type,
            reference_url=candidate.reference_url,
            location_key=(
                location_key(
                    candidate.company_name,
                    candidate.address,
                    candidate.reference_url or candidate.website_url or "",
                )
                if candidate.record_type == "location"
                else ""
            ),
            protected_fields=(
                ["company_name", "address"] if candidate.record_type == "location" else []
            ),
            website_url=candidate.website_url,
            domain=domain,
            address=candidate.address,
            phone=candidate.phone,
            email=candidate.email,
            source=candidate.collection_method or job.source,
            source_keyword=candidate.source_keyword or source_keyword,
            prefecture=candidate.prefecture,
            city=candidate.city,
            business_summary=candidate.business_summary,
            contact_url=candidate.contact_url,
            form_first_contact_url=candidate.form_first_contact_url,
            corporate_number=candidate.corporate_number,
        )
        try:
            with db.begin_nested():
                db.add(company)
                db.flush()
        except IntegrityError:
            job.duplicate_count += 1
            duplicate = duplicate_company(db, job.project_id, candidate)
            if duplicate:
                db.refresh(duplicate, with_for_update=True)
                observe_candidate(db, job, duplicate, candidate)
            mark_discovery(
                db, job, candidate, "DUPLICATE" if duplicate else "INGESTION_CONFLICT", duplicate
            )
        else:
            job.saved_count += 1
            if company.website_url and company.source != "form_first":
                saved_company_ids.append(company.id)
            observe_candidate(db, job, company, candidate, new=True)
            capture_candidate(db, job, candidate, company)
            mark_discovery(db, job, candidate, "SAVED", company)
    job.status = "completed"
    job.finished_at = datetime.now(timezone.utc)
    job.processing_ms = max(0, int((job.finished_at - job.created_at).total_seconds() * 1000))
    if before_commit:
        before_commit()
    db.commit()
    db.refresh(job)
    if saved_company_ids:
        from app.models import OperationJob
        from app.services.site_analysis import enqueue_site_analysis

        preserved = [job]
        if job.operation_job_id:
            operation = db.get(OperationJob, job.operation_job_id)
            if operation is not None:
                preserved.append(operation)

        enqueue_site_analysis(
            db,
            job.project_id,
            saved_company_ids,
            automatic=True,
            preserve_instances=tuple(preserved),
        )
        job = db.get(CollectionJob, collection_job_id)
        if job is None:
            raise RuntimeError("collection job disappeared after enqueueing site analysis")
    logger.info(
        "collection job end: id=%s status=completed found=%s saved=%s duplicates=%s errors=%s",
        job.id,
        job.found_count,
        job.saved_count,
        job.duplicate_count,
        job.error_count,
    )
    return job


def fail_job(db: Session, job: CollectionJob, message: str) -> CollectionJob:
    job.status = "failed"
    job.error_count = max(job.error_count, 1)
    job.error_message = message[:500]
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    logger.info("collection job end: id=%s status=failed", job.id)
    return job
