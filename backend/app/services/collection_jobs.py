"""Persistence and deduplication for collection jobs."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CollectionJob, Company, SuppressionEntry
from app.services.collection import Candidate, canonicalize_url
from app.services.scraper import is_aggregator_domain

logger = logging.getLogger("leadhive")


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


def is_duplicate(db: Session, project_id: UUID, candidate: Candidate) -> bool:
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
        bool(conditions)
        and db.scalar(
            select(Company.id).where(Company.project_id == project_id, or_(*conditions)).limit(1)
        )
        is not None
    )


def is_suppressed(db: Session, project_id: UUID, candidate: Candidate) -> bool:
    conditions = []
    if candidate.website_url:
        _, domain = canonicalize_url(candidate.website_url)
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
            .where(SuppressionEntry.project_id == project_id, or_(*conditions))
            .limit(1)
        )
        is not None
    )


def save_candidates(
    db: Session,
    job: CollectionJob,
    candidates: list[Candidate],
    source_keyword: str = "",
    input_errors: int | list[dict[str, object]] = 0,
) -> CollectionJob:
    error_details = input_errors if isinstance(input_errors, list) else []
    error_count = len(input_errors) if isinstance(input_errors, list) else input_errors
    job.found_count = len(candidates) + error_count
    job.error_count = error_count
    job.import_errors = error_details
    for candidate in candidates:
        if candidate.website_url:
            _, candidate_domain = canonicalize_url(candidate.website_url)
            if is_aggregator_domain(candidate_domain):
                job.excluded_count += 1
                continue
        if is_duplicate(db, job.project_id, candidate) or is_suppressed(
            db, job.project_id, candidate
        ):
            job.duplicate_count += 1
            continue
        domain = None
        if candidate.website_url:
            candidate.website_url, domain = canonicalize_url(candidate.website_url)
        company = Company(
            project_id=job.project_id,
            company_name=candidate.company_name,
            website_url=candidate.website_url,
            domain=domain,
            address=candidate.address,
            phone=candidate.phone,
            email=candidate.email,
            source=job.source,
            source_keyword=source_keyword,
        )
        try:
            with db.begin_nested():
                db.add(company)
                db.flush()
        except IntegrityError:
            job.duplicate_count += 1
        else:
            job.saved_count += 1
    job.status = "completed"
    job.finished_at = datetime.now(timezone.utc)
    job.processing_ms = max(0, int((job.finished_at - job.created_at).total_seconds() * 1000))
    db.commit()
    db.refresh(job)
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
