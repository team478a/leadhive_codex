"""Persist observations before ingestion, and track derived ingestion outcomes."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select

from app.config import settings
from app.models import CollectionDiscoveryHit, CollectionJob
from app.services.collection import canonicalize_url
from app.services.discovery_capture import DiscoveryCapture
from app.services.presence_platforms import DOMAINS, classify
from app.services.scraper import is_aggregator_domain

SOCIAL = {"INSTAGRAM", "X", "FACEBOOK", "YOUTUBE", "TIKTOK"}
JOBS = {"INDEED", "KYUJIN_BOX"}


def classify_hit(snapshot: dict) -> tuple[str, str]:
    value = snapshot["link"]
    try:
        url, domain = canonicalize_url(value)
        if snapshot.get("redacted"):
            return "OTHER", "CREDENTIAL_URL"
    except (ValueError, UnicodeError):
        return "OTHER", "INVALID_URL"
    presence = classify(url)
    # Shared platform taxonomy also covers home/login/search URLs lacking a profile path.
    platform = (
        presence[0]
        if presence
        else next(
            (
                key
                for key, host in DOMAINS.items()
                if domain == host.encode("idna").decode()
                or domain.endswith("." + host.encode("idna").decode())
            ),
            None,
        )
    )
    if platform in SOCIAL or domain == "twitter.com" or domain.endswith(".twitter.com"):
        return "SOCIAL", "EXTERNAL_PLATFORM"
    if platform in JOBS:
        return "JOB_PR", "EXTERNAL_PLATFORM"
    if platform or is_aggregator_domain(domain):
        return "PORTAL_DIRECTORY", "EXTERNAL_PLATFORM"
    path = urlsplit(url).path.lower()
    if path.endswith((".pdf", ".jpg", ".png")):
        return "OTHER", "NON_HTML_CANDIDATE"
    if any(part in path.split("/") for part in ("blog", "article", "articles", "column")):
        return "ARTICLE", "PATH_HINT_REQUIRES_REVIEW"
    return "OFFICIAL_SITE_CANDIDATE", "OFFICIAL_IDENTITY_NOT_VERIFIED"


def persist_discovery(db, job: CollectionJob, buffer: DiscoveryCapture):
    if job.source != "serper" or not buffer.response_received:
        return
    # Serialize the operation ceiling across fetches. No lock is held during HTTP.
    if job.operation_job_id:
        from app.models import OperationJob

        operation = db.scalar(
            select(OperationJob).where(OperationJob.id == job.operation_job_id).with_for_update()
        )
        operation_ids = [job.operation_job_id]
        plan = (operation.payload or {}).get("query_plan") if operation else None
        if plan:
            from app.models import CollectionSearchAttempt

            root_id = UUID(plan["root_operation_id"])
            db.scalar(select(OperationJob.id).where(OperationJob.id == root_id).with_for_update())
            operation_ids = list(
                db.scalars(
                    select(CollectionSearchAttempt.operation_job_id)
                    .where(
                        CollectionSearchAttempt.root_operation_id == root_id,
                    )
                    .distinct()
                )
            )
        used = (
            db.scalar(
                select(func.count())
                .select_from(CollectionDiscoveryHit)
                .join(CollectionJob)
                .where(CollectionJob.operation_job_id.in_(operation_ids))
            )
            or 0
        )
    else:
        used = 0
    rows = buffer.rows[: max(0, settings.collection_discovery_max_operation_hits - used)]
    for values in rows:
        snapshot = {
            **values["snapshot"],
            "keyword": job.keyword,
            "region": job.region,
            "source": "serper",
        }
        kind, reason = classify_hit(snapshot)
        disposition = values["disposition"]
        if disposition == "CAPTURED" and reason in {"INVALID_URL", "CREDENTIAL_URL"}:
            disposition = "INVALID_URL"
        db.add(
            CollectionDiscoveryHit(
                **{**values, "snapshot": snapshot, "disposition": disposition},
                collection_job_id=job.id,
                classification=kind,
                classification_reason=reason,
                retain_until=datetime.now(timezone.utc)
                + timedelta(days=settings.collection_discovery_retention_days),
            )
        )
        if reason == "EXTERNAL_PLATFORM" and not snapshot.get("redacted"):
            from app.services.external_presence import capture_url

            capture_url(db, job.project_id, snapshot["link"], snapshot["link"], job=job)
    job.discovery_summary = dict(
        received_count=buffer.received_count,
        captured_count=len(rows),
        omitted_count=buffer.received_count - len(rows),
        response_limit=100,
        operation_limit=settings.collection_discovery_max_operation_hits,
        retention_days=settings.collection_discovery_retention_days,
        field_chars=settings.collection_discovery_field_chars,
    )
    db.commit()


def mark_discovery(db, job, candidate, disposition, company=None):
    if candidate.discovery_hit_id is None:
        return
    hit = db.get(CollectionDiscoveryHit, candidate.discovery_hit_id)
    if hit is None or hit.collection_job_id != job.id:
        return
    hit.disposition = disposition
    hit.company_id = company.id if company else None


def discovery_summary(db, job):
    if not job.discovery_summary:
        return {"available": False, "received_count": None, "captured_count": None}
    counts = Counter(
        db.scalars(
            select(CollectionDiscoveryHit.disposition).where(
                CollectionDiscoveryHit.collection_job_id == job.id
            )
        )
    )
    kinds = Counter(
        db.scalars(
            select(CollectionDiscoveryHit.classification).where(
                CollectionDiscoveryHit.collection_job_id == job.id
            )
        )
    )
    return {
        "available": True,
        **job.discovery_summary,
        "dispositions": dict(counts),
        "classifications": dict(kinds),
    }
