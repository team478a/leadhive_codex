"""Persist observations before ingestion, and track derived ingestion outcomes."""

import re
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select

from app.config import settings
from app.models import (
    CollectionDiscoveryHit,
    CollectionJob,
    FormDmReadinessResult,
    LeadProcessingUsage,
    OperationJob,
)
from app.services.collection import Candidate, canonicalize_url
from app.services.discovery_capture import DiscoveryCapture
from app.services.presence_platforms import DOMAINS, classify
from app.services.scraper import is_aggregator_domain

SOCIAL = {"INSTAGRAM", "X", "FACEBOOK", "YOUTUBE", "TIKTOK"}
JOBS = {"INDEED", "KYUJIN_BOX"}
# These are sources about providers, not the provider's own website. Keep their
# Raw observations without creating Company records from Serper results.
THIRD_PARTY_DOMAINS = {
    "web-kanji.com",
    "probel.jp",
    "dreamnews.jp",
    "lemon8-app.com",
    "livejapan.com",
    "gurumeguide.cpay.jp",
    "travelbook.co.jp",
    "retty.me",
    "jalan.net",
    "tabiiro.jp",
    "precious.jp",
    "kit-press.com",
}


class QueryTypeTotals(TypedDict):
    search_results: int
    contact_candidates: int
    candidate_rate_percent: float | None
    search_requests: int
    low_effect: bool


JOB_SOURCE_DOMAINS = {"townwork.net", "baitoru.com", "next.rikunabi.com", "r-agent.com"}
ARTICLE_PATH_SEGMENTS = {"blog", "blogs", "article", "articles", "column", "columns"}
COMPARISON_TITLE_MARKERS = {
    "会社比較",
    "企業比較",
    "会社一覧",
    "企業一覧",
    "会社ランキング",
    "企業ランキング",
}
NUMBERED_SELECTION_MARKERS = {
    "0選",
    "1選",
    "2選",
    "3選",
    "4選",
    "5選",
    "6選",
    "7選",
    "8選",
    "9選",
    "０選",
    "１選",
    "２選",
    "３選",
    "４選",
    "５選",
    "６選",
    "７選",
    "８選",
    "９選",
}


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
    if platform in JOBS or any(
        domain == host or domain.endswith("." + host) for host in JOB_SOURCE_DOMAINS
    ):
        return "JOB_PR", "EXTERNAL_PLATFORM"
    if (
        platform
        or is_aggregator_domain(domain)
        or any(domain == host or domain.endswith("." + host) for host in THIRD_PARTY_DOMAINS)
    ):
        return "PORTAL_DIRECTORY", "EXTERNAL_PLATFORM"
    path = urlsplit(url).path.lower()
    if path.endswith((".pdf", ".jpg", ".png")):
        return "OTHER", "NON_HTML_CANDIDATE"
    title = snapshot.get("title") or ""
    # Match combinations, not isolated industry/job/blog words. Reject this
    # result page only; a provider's own domain may also publish list articles.
    own_offering = re.search(
        r"(?:当社|弊社|自社|当店|当院)|(?:おすすめ|人気|厳選).{0,8}"
        r"(?:プラン|メニュー|自社サービス)|(?:支援|導入|対応)実績|"
        r"(?:比較|まとめ)サイト(?:の)?(?:制作|開発|構築|運営支援)|ランキング(?:改善|向上|対策)",
        title,
    )
    if not own_offering and (
        (
            re.search(r"[0-9０-９]+\s*選", title)
            and re.search(r"おすすめ|オススメ|お勧め|厳選|比較|ランキング|人気", title)
        )
        or (
            re.search(
                r"(?:会社|企業|業者)\s*[0-9０-９]+\s*社(?!\s*(?:を|に|へ|の)?\s*(?:支援|導入|対応|実績))",
                title,
            )
            and re.search(r"おすすめ|オススメ|厳選|比較|ランキング", title)
        )
        or re.search(r"(?:周辺|近郊|エリア別).{0,40}(?:一覧|ランキング)", title)
        or re.search(r"(?:おすすめ|オススメ|人気|厳選).{0,40}ランキング", title)
        or re.search(r"ランキング\s*(?:TOP|トップ)\s*[0-9０-９]+", title, re.IGNORECASE)
        or re.search(r"(?:比較|口コミ|評判).{0,12}ランキング|(?:まとめ|比較)サイト", title)
        or re.search(r"(?:おすすめ|厳選).{0,40}(?:編集部|まとめ記事)", title)
    ):
        return "ARTICLE", "AGGREGATION_TITLE"
    if any(part in path.split("/") for part in ARTICLE_PATH_SEGMENTS):
        return "ARTICLE", "PATH_HINT_REQUIRES_REVIEW"
    # Job-result pages describe vacancies, not the business's service offering.
    # Do not reject a provider merely because its own recruitment page mentions jobs.
    if re.search(r"の求人[・\s]+仕事[・\s]+採用", title):
        return "JOB_PR", "TITLE_HINT_REQUIRES_REVIEW"
    if (
        any(marker in title for marker in COMPARISON_TITLE_MARKERS)
        or re.search(r"(?:会社|企業)\s*(?:の)?\s*おすすめ(?!\s*(?:プラン|サービス))", title)
        or re.search(r"依頼先\s*(?:の)?\s*比較", title)
        or (
            any(marker in title for marker in NUMBERED_SELECTION_MARKERS)
            and any(marker in title for marker in ("会社", "企業", "おすすめ", "比較", "厳選"))
        )
        or (
            # A numbered provider list, not a provider's customer/support count.
            re.search(
                r"(?:会社|企業)\s*[0-9０-９]+\s*社"
                r"(?!\s*(?:を|に|へ|の)?\s*(?:支援|導入|対応|実績))",
                title,
            )
            and any(marker in title for marker in ("おすすめ", "比較", "厳選", "ランキング"))
        )
    ):
        return "ARTICLE", "COMPARISON_TITLE_REQUIRES_REVIEW"
    return "OFFICIAL_SITE_CANDIDATE", "OFFICIAL_IDENTITY_NOT_VERIFIED"


def classify_candidate(candidate: Candidate) -> tuple[str, str]:
    """Use the same search title at quota selection and ingestion as in the Raw ledger."""
    return classify_hit({"link": candidate.website_url or "", "title": candidate.company_name})


def persist_discovery(db, job: CollectionJob, buffer: DiscoveryCapture):
    if job.source != "serper" or not buffer.response_received:
        return
    from app.services.collection_runtime import runtime_snapshot

    claim = None
    # Serialize the operation ceiling across fetches. No lock is held during HTTP.
    if job.operation_job_id:
        from app.models import OperationJob

        operation = db.scalar(
            select(OperationJob).where(OperationJob.id == job.operation_job_id).with_for_update()
        )
        operation_ids = [job.operation_job_id]
        claim = (operation.payload or {}).get("collection_runtime") if operation else None
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
        runtime=runtime_snapshot(),
        collection_claim=claim,
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
    hits = CollectionDiscoveryHit
    metadata = hits.form_first_metadata
    query_type = metadata["form_first_query_type"].astext
    is_candidate = metadata["form_first_candidate"].astext == "true"
    form_status = metadata["form_first_form_status"].astext
    corporate_status = metadata["form_first_corporate_check"].astext
    url_added = metadata["form_first_existing_url_added"].astext == "true"
    groups = db.execute(
        select(
            hits.disposition,
            hits.classification,
            hits.classification_reason,
            query_type,
            is_candidate,
            form_status,
            corporate_status,
            func.count(),
        )
        .where(hits.collection_job_id == job.id)
        .group_by(
            hits.disposition,
            hits.classification,
            hits.classification_reason,
            query_type,
            is_candidate,
            form_status,
            corporate_status,
        )
    ).all()
    dispositions: dict[str, int] = {}
    kinds: dict[str, int] = {}
    reasons: dict[str, int] = {}
    type_totals: dict[str, QueryTypeTotals] = {}
    corporate_checks: dict[str, int] = {}
    candidate_count = form_found_count = reservation_form_count = 0
    for disposition, classification, reason, kind, candidate, status, corporate, count in groups:
        dispositions[disposition] = dispositions.get(disposition, 0) + count
        kinds[classification] = kinds.get(classification, 0) + count
        reasons[reason] = reasons.get(reason, 0) + count
        if kind:
            totals = type_totals.setdefault(
                kind,
                {
                    "search_results": 0,
                    "contact_candidates": 0,
                    "candidate_rate_percent": None,
                    "search_requests": 0,
                    "low_effect": False,
                },
            )
            totals["search_results"] += count
            if candidate:
                totals["contact_candidates"] += count
        if candidate:
            candidate_count += count
        if status in {"FORM_FOUND", "FORM_JS_SUSPECTED", "RESERVATION_FORM"}:
            form_found_count += count
        if status == "RESERVATION_FORM":
            reservation_form_count += count
        if corporate:
            corporate_checks[corporate] = corporate_checks.get(corporate, 0) + count

    search_request_count = (
        db.scalar(
            select(func.count(LeadProcessingUsage.id)).where(
                LeadProcessingUsage.collection_job_id == job.id,
                LeadProcessingUsage.kind == "search",
                LeadProcessingUsage.provider == "serper",
            )
        )
        or 0
    )
    operation = db.get(OperationJob, job.operation_job_id) if job.operation_job_id else None
    payload = operation.payload if operation else {}
    collection_method = (payload or {}).get("collection_method", "company_first")
    query_map = (payload or {}).get("form_first_query_map") or {}
    request_query_type = (query_map.get(job.keyword) or {}).get("query_type")
    for query in query_map.values():
        kind = query.get("query_type")
        if kind:
            type_totals.setdefault(
                kind,
                {
                    "search_results": 0,
                    "contact_candidates": 0,
                    "candidate_rate_percent": None,
                    "search_requests": 0,
                    "low_effect": False,
                },
            )
    for kind, totals in type_totals.items():
        results = totals["search_results"]
        candidates = totals["contact_candidates"]
        totals["candidate_rate_percent"] = round(candidates * 100 / results, 1) if results else None
        totals["search_requests"] = search_request_count if kind == request_query_type else 0
        totals["low_effect"] = bool(results and candidates * 100 / results < 20)

    existing_url_added_count = (
        db.scalar(
            select(func.count(func.distinct(hits.company_id))).where(
                hits.collection_job_id == job.id,
                hits.company_id.is_not(None),
                url_added,
            )
        )
        or 0
    )
    newly_registered_count = (
        db.scalar(
            select(func.count(func.distinct(hits.company_id))).where(
                hits.collection_job_id == job.id,
                hits.company_id.is_not(None),
                hits.disposition == "SAVED",
            )
        )
        or 0
    )
    readiness_job_id = db.scalar(
        select(OperationJob.id)
        .where(
            OperationJob.project_id == job.project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status == "completed",
        )
        .order_by(OperationJob.finished_at.desc(), OperationJob.created_at.desc())
        .limit(1)
    )
    sendable_count = None
    if readiness_job_id:
        sendable_count = (
            db.scalar(
                select(func.count(func.distinct(FormDmReadinessResult.company_id)))
                .join(hits, hits.company_id == FormDmReadinessResult.company_id)
                .where(
                    FormDmReadinessResult.job_id == readiness_job_id,
                    FormDmReadinessResult.primary_reason.in_(("READY", "BROWSER_READY")),
                    hits.collection_job_id == job.id,
                )
            )
            or 0
        )
    metrics = {
        "collection_method": collection_method,
        "search_request_count": search_request_count,
        "contact_page_candidate_count": candidate_count,
        "form_found_count": form_found_count,
        "reservation_form_count": reservation_form_count,
        "newly_registered_company_count": newly_registered_count,
        "existing_contact_url_added_company_count": existing_url_added_count,
        "corporate_checks": {
            "MATCHED": corporate_checks.get("CORPORATE_NUMBER_MATCHED", 0),
            "AMBIGUOUS": corporate_checks.get("CORPORATE_NUMBER_AMBIGUOUS", 0),
            "NOT_FOUND": corporate_checks.get("CORPORATE_NUMBER_NOT_FOUND", 0),
            "SKIPPED": corporate_checks.get("CORPORATE_CHECK_SKIPPED", 0),
            "ERROR": corporate_checks.get("CORPORATE_CHECK_ERROR", 0),
        },
        "exclusion_reasons": reasons,
        "query_types": type_totals,
        "sendable_company_count": sendable_count,
        "sendable_companies_per_100_searches": (
            round(sendable_count * 100 / search_request_count, 1)
            if sendable_count is not None and search_request_count
            else None
        ),
    }
    return {
        "available": True,
        **job.discovery_summary,
        "dispositions": dispositions,
        "classifications": kinds,
        "metrics": metrics,
    }
