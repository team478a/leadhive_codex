"""Passive capture + bounded extra search. Presence never authorizes outreach."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import (
    Company,
    ExternalPresence,
    ExternalPresenceEvidence,
    ExternalPresenceSearch,
    LeadSourceObservation,
    Project,
)
from app.schema_external_presence import PresenceSearchPlan
from app.services.lead_identity import identity_hash, normalize
from app.services.presence_platforms import DOMAINS, classify

SOCIAL_FIELDS = {
    "INSTAGRAM": "instagram_url",
    "X": "x_url",
    "FACEBOOK": "facebook_url",
    "YOUTUBE": "youtube_url",
    "TIKTOK": "tiktok_url",
}


def presence_context_hash(company):
    protected = set(company.protected_fields or [])
    context = [
        identity_hash(company),
        {field: getattr(company, field) for field in SOCIAL_FIELDS.values() if field in protected},
    ]
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def inventory(db, company_id):
    current_hash = presence_context_hash(db.get(Company, company_id))
    rows = {
        r.platform: r
        for r in db.scalars(
            select(ExternalPresence).where(ExternalPresence.company_id == company_id)
        )
    }
    return [
        dict(
            platform=p,
            status=(rows[p].status if rows[p].identity_hash == current_hash else "ERROR")
            if p in rows
            else "NOT_CHECKED",
            url=rows[p].url if p in rows else "",
            source_url=rows[p].source_url if p in rows else "",
            discovery_method=rows[p].discovery_method if p in rows else None,
            observed_at=rows[p].observed_at if p in rows else None,
            last_verified_at=rows[p].last_verified_at if p in rows else None,
            reason=(rows[p].reason if rows[p].identity_hash == current_hash else "ENTITY_CHANGED")
            if p in rows
            else "",
        )
        for p in DOMAINS
    ]


def set_status(
    db,
    company,
    platform,
    status,
    *,
    url="",
    source_url="",
    method="PASSIVE",
    reason="",
    human_verified=False,
):
    db.scalar(select(Company.id).where(Company.id == company.id).with_for_update())
    row = db.scalar(
        select(ExternalPresence).where(
            ExternalPresence.company_id == company.id, ExternalPresence.platform == platform
        )
    )
    field = SOCIAL_FIELDS.get(platform)
    protected_conflict = (
        not human_verified
        and field is not None
        and field in (company.protected_fields or [])
        and url != getattr(company, field, "")
        and status == "FOUND"
    )
    if protected_conflict:
        if row is not None:
            return row
        status, reason, url = "ERROR", "PROTECTED_PRESENCE_CONFLICT", ""
    if row is None:
        row = ExternalPresence(company_id=company.id, platform=platform, status=status)
        db.add(row)
    elif not human_verified and db.scalar(
        select(ExternalPresenceEvidence.id)
        .where(
            ExternalPresenceEvidence.company_id == company.id,
            ExternalPresenceEvidence.url == row.url,
            ExternalPresenceEvidence.actor_user_id.is_not(None),
        )
        .limit(1)
    ):
        return row  # Automatic observations cannot overwrite a Human-selected presence.
    elif (
        row.status == "FOUND"
        and status != "FOUND"
        and row.identity_hash == presence_context_hash(company)
    ):
        return row  # A failed/empty later search does not erase a positive observation.
    row.status, row.reason = status, reason
    row.identity_hash = presence_context_hash(company)
    row.discovery_method = method
    if status == "FOUND":
        row.url, row.source_url = url, source_url
        row.observed_at = datetime.now(timezone.utc)
        row.last_verified_at = row.observed_at
    return row


def capture_url(
    db,
    project_id,
    value,
    source_url,
    *,
    company=None,
    job=None,
    method="PASSIVE",
    actor_user_id=None,
):
    classified = classify(value)
    if classified is None or (job is not None and job.source == "google_places"):
        return  # Do not introduce a second persistent copy of Places content.
    if company is not None and company.project_id != project_id:
        raise ValueError("Project mismatch")
    if job is not None and job.project_id != project_id:
        raise ValueError("Project mismatch")
    platform, url = classified
    duplicate = db.scalar(
        select(ExternalPresenceEvidence.id)
        .where(
            ExternalPresenceEvidence.project_id == project_id,
            ExternalPresenceEvidence.collection_job_id == (job.id if job else None),
            ExternalPresenceEvidence.company_id == (company.id if company else None),
            ExternalPresenceEvidence.url == url,
            ExternalPresenceEvidence.discovery_method == method,
        )
        .limit(1)
    )
    if not duplicate or actor_user_id is not None:
        db.add(
            ExternalPresenceEvidence(
                project_id=project_id,
                company_id=company.id if company else None,
                collection_job_id=job.id if job else None,
                platform=platform,
                actor_user_id=actor_user_id,
                url=url,
                source_url=source_url,
                discovery_method=method,
                association="HUMAN_VERIFIED"
                if actor_user_id
                else "CONFIRMED"
                if company
                else "REVIEW_REQUIRED",
            )
        )
    if company:
        set_status(
            db,
            company,
            platform,
            "FOUND",
            url=url,
            source_url=source_url,
            method=method,
            human_verified=actor_user_id is not None,
        )


def capture_candidate(db, job, candidate, company=None):
    urls = list(candidate.presence_urls)
    # Candidate URL alone is a search observation, not a verified Company association.
    for value in (candidate.website_url, candidate.reference_url):
        if value:
            capture_url(db, job.project_id, value, value, job=job)
            if classify(value):
                matches = [
                    c
                    for c in db.scalars(
                        select(Company).where(
                            Company.project_id == job.project_id,
                            func.length(Company.phone) >= 9,
                            func.strpos(
                                normalize(candidate.company_name + candidate.search_excerpt),
                                func.regexp_replace(Company.phone, "[^0-9]", "", "g"),
                            )
                            > 0,
                        )
                    )
                    if matches_company(c, candidate)
                ]
                if len(matches) == 1:
                    capture_url(db, job.project_id, value, value, job=job, company=matches[0])
    if company:
        for value in urls:
            capture_url(
                db,
                job.project_id,
                value,
                candidate.website_url or candidate.reference_url,
                company=company,
                job=job,
            )


def matches_company(company, candidate):
    # Do not merge/verify a social account on name similarity alone.
    text = normalize(candidate.company_name + " " + candidate.search_excerpt)
    name, phone, address = (
        normalize(v) for v in (company.company_name, company.phone, company.address)
    )
    return (
        len(name) >= 3
        and name in text
        and (
            (len(phone) >= 9 and phone in text)
            or (len(address) >= 8 and any(c.isdigit() for c in address) and address in text)
        )
    )


def extra_searches(
    db,
    job,
    plan: PresenceSearchPlan,
    *,
    stopped=lambda: False,
    budget_job_id=None,
    eligible=lambda company: True,
):
    from app.services.collection import ExternalServiceError, search_serper
    from app.services.processing_usage import capture_usage, persist_usage

    company_ids = select(LeadSourceObservation.company_id).where(
        LeadSourceObservation.collection_job_id == job.id
    )
    companies = db.scalars(
        select(Company)
        .where(Company.project_id == job.project_id, Company.id.in_(company_ids))
        .order_by(Company.id)
    ).all()
    order = sorted(DOMAINS, key=lambda p: (plan.mode(p) != "REQUIRED", p))
    for company in companies:
        for platform in order:
            mode = plan.mode(platform)
            if mode == "AUTO":
                continue
            if stopped():
                return
            if not eligible(company):
                break  # Known MUST failure / EXCLUDE match: no further investigation.
            if job.source == "google_places":
                set_status(db, company, platform, "ERROR", reason="SOURCE_TERMS_REVIEW_REQUIRED")
                db.commit()
                continue
            current = db.scalar(
                select(ExternalPresence).where(
                    ExternalPresence.company_id == company.id, ExternalPresence.platform == platform
                )
            )
            if (
                current
                and current.status == "FOUND"
                and current.identity_hash == presence_context_hash(company)
                and (
                    mode != "REQUIRED"
                    or (
                        current.observed_at is not None
                        and current.observed_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                    )
                )
            ):
                continue
            db.scalar(
                select(Project.id)
                .where(Project.id == job.project_id)
                .with_for_update(key_share=True)
            )
            scope = (
                ExternalPresenceSearch.operation_job_id == job.operation_job_id
                if job.operation_job_id
                else (ExternalPresenceSearch.budget_job_id == (budget_job_id or job.id))
            )
            if db.scalar(
                select(ExternalPresenceSearch.id).where(
                    ExternalPresenceSearch.collection_job_id == job.id,
                    ExternalPresenceSearch.company_id == company.id,
                    ExternalPresenceSearch.platform == platform,
                )
            ):
                continue
            count = (
                db.scalar(select(func.count()).select_from(ExternalPresenceSearch).where(scope))
                or 0
            )
            started = (
                db.scalar(select(func.min(ExternalPresenceSearch.created_at)).where(scope))
                or job.created_at
            )
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            if count >= plan.max_extra_searches or elapsed >= plan.timeout_seconds:
                set_status(db, company, platform, "ERROR", reason="SEARCH_BUDGET_EXHAUSTED")
                db.commit()
                continue
            attempt = ExternalPresenceSearch(
                collection_job_id=job.id,
                operation_job_id=job.operation_job_id,
                budget_job_id=budget_job_id or job.id,
                company_id=company.id,
                platform=platform,
            )
            db.add(attempt)
            method = "REQUIRED_VERIFICATION" if mode == "REQUIRED" else "EXPLICIT_SEARCH"
            set_status(db, company, platform, "ERROR", method=method, reason="SEARCH_INCOMPLETE")
            # Reserve before network I/O; interrupted attempts must still consume budget.
            db.commit()
            identity = company.phone or company.address
            query = f"{company.company_name} {identity} site:{DOMAINS[platform]}"
            with capture_usage() as usage:
                try:
                    candidates = search_serper(query, "", 5)
                    matched = False
                    uncertain = False
                    for candidate in candidates:
                        found = classify(candidate.website_url or "")
                        if not found or found[0] != platform:
                            continue
                        associated = matches_company(company, candidate)
                        capture_url(
                            db,
                            job.project_id,
                            found[1],
                            found[1],
                            company=company if associated else None,
                            job=job,
                            method=method,
                        )
                        matched |= associated
                        uncertain |= not associated
                    if not matched:
                        set_status(
                            db,
                            company,
                            platform,
                            "ERROR" if uncertain else "NOT_FOUND",
                            method=method,
                            reason="ENTITY_UNCERTAIN" if uncertain else "SEARCH_NO_MATCH",
                        )
                    attempt.status = "COMPLETED"
                except ExternalServiceError:
                    attempt.status, attempt.reason = "ERROR", "SEARCH_FAILED"
                    set_status(
                        db, company, platform, "ERROR", method=method, reason="SEARCH_FAILED"
                    )
                finally:
                    persist_usage(db, usage, job.project_id, collection_job_id=job.id)
            db.commit()


def capture_website_links(db, company, data, source_url):
    for field in ("instagram_url", "x_url", "facebook_url", "youtube_url", "tiktok_url"):
        value = getattr(data, field, "")
        if value:
            capture_url(db, company.project_id, value, source_url, company=company)
