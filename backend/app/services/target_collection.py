"""Count-driven Serper discovery, bounded and resumable without outbound work."""

from uuid import UUID

from sqlalchemy import select

from app.models import CollectionJob, Company, LeadSourceObservation
from app.schema_external_presence import PresenceSearchPlan
from app.services.collection import ExternalServiceError, canonicalize_url, search_serper_page
from app.services.collection_conditions import evaluate
from app.services.collection_discovery import classify_candidate, mark_discovery, persist_discovery
from app.services.collection_jobs import (
    fail_job,
    is_duplicate,
    is_suppressed,
    save_candidates,
    start_job,
)
from app.services.discovery_capture import capturing_discovery
from app.services.external_presence import extra_searches
from app.services.processing_usage import capture_usage, persist_usage
from app.services.scraper import is_aggregator_domain

REQUEST_BUDGET = 50
PAGE_SIZE = 10


def collection_inventory(db, job, conditions):
    scope = (job.payload.get("collection_progress") or {}).get("operation_ids", [])
    operation_ids = {UUID(value) for value in scope} | {job.id}
    rows = db.scalars(
        select(Company)
        .join(LeadSourceObservation, LeadSourceObservation.company_id == Company.id)
        .join(CollectionJob, CollectionJob.id == LeadSourceObservation.collection_job_id)
        .where(
            CollectionJob.operation_job_id.in_(operation_ids),
            Company.project_id == job.project_id,
            LeadSourceObservation.identity_reasons.contains(["SINGLE_SOURCE_DISCOVERY"]),
            Company.analysis_status.notin_(("duplicate", "excluded")),
        )
        .distinct()
    ).all()
    return {
        str(company.id): evaluate(db, company, conditions)["state"] if conditions else "MATCH"
        for company in rows
    }


def collected_companies(db, job, conditions):
    return {
        company_id
        for company_id, state in collection_inventory(db, job, conditions).items()
        if state == "MATCH"
    }


def bounded_candidates(db, job, candidates, remaining):
    """Do not overshoot the goal; retain duplicate/excluded observations for ingestion."""
    selected = []
    keys: set[str | tuple[str, str]] = set()
    for candidate in candidates:
        domain = canonicalize_url(candidate.website_url)[1] if candidate.website_url else ""
        if (
            is_duplicate(db, job.project_id, candidate)
            or is_suppressed(db, job.project_id, candidate)
            or (domain and is_aggregator_domain(domain))
            or (
                candidate.website_url
                and classify_candidate(candidate)[0]
                in {"SOCIAL", "JOB_PR", "PORTAL_DIRECTORY", "OTHER", "ARTICLE"}
            )
        ):
            selected.append(candidate)
            continue
        key = domain or (candidate.company_name, candidate.address)
        if key in keys or len(keys) < remaining:
            keys.add(key)
            selected.append(candidate)
        else:
            mark_discovery(db, job, candidate, "TARGET_LIMIT")
    return selected


def run(db, job, payload, conditions, stopped):
    target = payload["target_count"]
    state = dict(job.payload.get("collection_progress") or {})
    budget = min(
        REQUEST_BUDGET,
        state.get("request_budget", payload.get("search_request_limit") or REQUEST_BUDGET),
    )
    index = state.get("keyword_index", 0)
    page = state.get("next_page", 1)
    requests = state.get("requests", 0)
    query_stops = list(state.get("query_stops", []))
    operation_ids = sorted(set(state.get("operation_ids", [])) | {str(job.id)})

    def record(reason=None):
        nonlocal state
        inventory = collection_inventory(db, job, conditions)
        state = dict(
            target_count=target,
            collected_count=sum(value == "MATCH" for value in inventory.values()),
            discovered_count=len(inventory),
            review_required_count=sum(value == "REVIEW_REQUIRED" for value in inventory.values()),
            no_match_count=sum(value == "NO_MATCH" for value in inventory.values()),
            conditions_applied=bool(conditions),
            requests=requests,
            request_budget=budget,
            keyword_index=index,
            next_page=page,
            query_stops=query_stops,
            operation_ids=operation_ids,
            stop_reason=reason,
        )
        job.payload = {**job.payload, "collection_progress": state}
        db.commit()

    record()
    while index < len(payload["keywords"]):
        if stopped():
            return
        if state["collected_count"] >= target:
            record("TARGET_REACHED")
            return
        if requests >= budget:
            record("REQUEST_BUDGET_REACHED")
            return
        keyword = payload["keywords"][index]
        collection = start_job(
            db, job.project_id, "serper", keyword, payload["region"], operation_job_id=job.id
        )
        before_inventory = collection_inventory(db, job, conditions)
        before = {key for key, value in before_inventory.items() if value == "MATCH"}
        # Reserve the attempt before HTTP, retaining the ceiling after a crash/retry.
        requests += 1
        record()
        with capture_usage() as usage, capturing_discovery() as discovery:
            try:
                candidates = search_serper_page(keyword, payload["region"], PAGE_SIZE, page)
                error = None
            except ExternalServiceError as exc:
                candidates, error = [], exc
        persist_discovery(db, collection, discovery)
        persist_usage(db, usage, job.project_id, collection_job_id=collection.id)
        if stopped():
            fail_job(db, collection, "収集が中断されました。")
            return
        if error:
            fail_job(db, collection, error.public_message)
            job.failed_count += 1
            record("SOURCE_ERROR")
            return
        save_candidates(
            db,
            collection,
            bounded_candidates(db, collection, candidates, target - len(before)),
            keyword,
        )
        collection.found_count = len(candidates)
        db.commit()
        if payload.get("presence_search"):
            collection.presence_search_plan = payload["presence_search"]
            db.commit()
            extra_searches(
                db,
                collection,
                PresenceSearchPlan.model_validate(payload["presence_search"]),
                budget_job_id=db.scalar(
                    select(CollectionJob.id)
                    .where(
                        CollectionJob.operation_job_id.in_([UUID(value) for value in operation_ids])
                    )
                    .order_by(CollectionJob.created_at, CollectionJob.id)
                    .limit(1)
                ),
                stopped=stopped,
                eligible=lambda company: (
                    not conditions or evaluate(db, company, conditions)["state"] != "NO_MATCH"
                ),
            )
        if stopped():
            return
        after_inventory = collection_inventory(db, job, conditions)
        job.processed_count += 1
        job.success_count += 1
        # A newly saved REVIEW_REQUIRED/NO_MATCH candidate is still discovery growth.
        # Human review latency must not masquerade as an exhausted search page.
        if not (after_inventory.keys() - before_inventory.keys()):
            query_stops.append(dict(keyword=keyword, page=page, reason="NO_NEW_TARGETS"))
            index, page = index + 1, 1
        else:
            page += 1
        record()
    record("TARGET_REACHED" if state["collected_count"] >= target else "QUERIES_EXHAUSTED")
