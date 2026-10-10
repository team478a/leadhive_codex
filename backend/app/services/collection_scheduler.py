"""Fair bounded search; reservation before HTTP, ingestion/cursor in one transaction.

The operation lease fences ingestion. A lost reservation costs budget and becomes
UNKNOWN. Repeating a search needs a new reservation; network exactly-once is not claimed.
"""

import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select

from app.models import CollectionJob, CollectionQueryTask, CollectionSearchAttempt, OperationJob
from app.schema_external_presence import PresenceSearchPlan
from app.services import target_collection
from app.services.collection import ExternalServiceError, search_serper_page
from app.services.collection_discovery import persist_discovery
from app.services.collection_jobs import save_candidates
from app.services.collection_query_plan import (
    MAX_PAGE_ATTEMPTS,
    PAGE_SIZE,
    REQUEST_BUDGET,
    VERSION,
    plan_hash,
    plan_snapshot,
    planned_queries,
)
from app.services.collection_search_policy import choose_task, successful_page
from app.services.discovery_capture import capturing_discovery
from app.services.external_presence import extra_searches
from app.services.processing_usage import capture_usage, persist_usage


class LostSearchLease(Exception):
    pass


def fence(db, job, worker_id):
    db.refresh(job, with_for_update=True)
    if (
        job.status != "running"
        or job.worker_id != worker_id
        or job.cancel_requested
        or job.lease_expires_at is None
        or job.lease_expires_at <= datetime.now(timezone.utc)
    ):
        raise LostSearchLease()


def root_and_tasks(db, job, worker_id):
    plan = job.payload["query_plan"]
    if (
        plan["snapshot"]["version"] != VERSION
        or plan_hash(plan_snapshot(job.payload)) != plan["hash"]
    ):
        raise ValueError("Collection plan changed")
    # All cursor mutations use the root lock, after the executing operation lock.
    fence(db, job, worker_id)
    root = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.id == UUID(plan["root_operation_id"]),
            OperationJob.project_id == job.project_id,
        )
        .with_for_update()
    )
    if root is None or root.payload.get("query_plan") != plan:
        raise ValueError("Collection root does not match immutable plan")
    tasks = list(
        db.scalars(
            select(CollectionQueryTask)
            .where(
                CollectionQueryTask.root_operation_id == root.id,
            )
            .order_by(CollectionQueryTask.query_order)
        )
    )
    if not tasks:
        for order, (keyword, region) in enumerate(planned_queries(plan["snapshot"])):
            db.add(
                CollectionQueryTask(
                    root_operation_id=root.id,
                    project_id=job.project_id,
                    plan_hash=plan["hash"],
                    query_order=order,
                    keyword=keyword,
                    region=region,
                )
            )
        db.flush()
        tasks = list(
            db.scalars(
                select(CollectionQueryTask)
                .where(
                    CollectionQueryTask.root_operation_id == root.id,
                )
                .order_by(CollectionQueryTask.query_order)
            )
        )
    attempts = list(
        db.scalars(
            select(CollectionSearchAttempt)
            .where(
                CollectionSearchAttempt.root_operation_id == root.id,
            )
            .order_by(CollectionSearchAttempt.attempt_order)
        )
    )
    return root, tasks, attempts


def fail_attempt(
    db, attempt, task, reason, *, unknown=False, retryable=False, delay=0, message=None
):
    attempt.state = "UNKNOWN" if unknown else "FAILED"
    attempt.reason, attempt.finished_at = reason, datetime.now(timezone.utc)
    collection = db.get(CollectionJob, attempt.collection_job_id)
    collection.status = "failed"
    collection.error_message = (message or "検索結果を確定できませんでした。")[:500]
    collection.error_count, collection.finished_at = 1, attempt.finished_at
    used = (
        db.scalar(
            select(func.count())
            .select_from(CollectionSearchAttempt)
            .where(
                CollectionSearchAttempt.task_id == task.id,
                CollectionSearchAttempt.page == attempt.page,
            )
        )
        or 0
    )
    if retryable and used < MAX_PAGE_ATTEMPTS and delay <= 60:
        task.not_before = datetime.now(timezone.utc) + timedelta(seconds=max(2**used, delay))
    else:
        task.state, task.stop_reason = "SOURCE_ERROR", reason


def summarize(db, job, root, tasks, attempts, conditions, reason=None):
    # Scope all retries through recorded attempt parents, not mutable Raw hits.
    ids = sorted({str(root.id), str(job.id)} | {str(a.operation_job_id) for a in attempts})
    job.payload = {**job.payload, "collection_progress": {"operation_ids": ids}}
    inventory = target_collection.collection_inventory(db, job, conditions)
    successes = sum(a.state == "SUCCEEDED" for a in attempts)
    failed_queries = sum(t.state == "SOURCE_ERROR" for t in tasks)
    job.processed_count = successes
    job.success_count = successes
    job.failed_count = failed_queries
    pending = sum(t.state == "READY" for t in tasks)
    capped = sum(t.stop_reason == "QUERY_PAGE_LIMIT" for t in tasks)
    job.payload = {
        **job.payload,
        "collection_progress": dict(
            operation_ids=ids,
            scheduler_version=VERSION,
            target_count=job.payload["target_count"],
            collected_count=sum(v == "MATCH" for v in inventory.values()),
            discovered_count=len(inventory),
            review_required_count=sum(v == "REVIEW_REQUIRED" for v in inventory.values()),
            no_match_count=sum(v == "NO_MATCH" for v in inventory.values()),
            conditions_applied=bool(conditions),
            requests=len(attempts),
            request_budget=min(
                REQUEST_BUDGET, root.payload["query_plan"]["snapshot"]["request_budget"]
            ),
            stop_reason=reason,
            coverage_status="PARTIAL"
            if pending or failed_queries or capped
            else "SEARCHES_STOPPED",
            planned_queries=len(tasks),
            unsearched_queries=sum(t.last_attempt_order == 0 for t in tasks),
            pending_queries=pending,
            failed_queries=failed_queries,
            capped_queries=capped,
            unknown_attempts=sum(a.state == "UNKNOWN" for a in attempts),
            queries=[
                dict(
                    keyword=t.keyword,
                    region=t.region,
                    next_page=t.next_page,
                    stagnant_pages=t.stagnant_pages,
                    state=t.state,
                    stop_reason=t.stop_reason,
                )
                for t in tasks
            ],
            region_mode=root.payload["query_plan"]["snapshot"].get("region_mode", "literal"),
            planned_regions=len({t.region for t in tasks}),
            unsearched_regions=len({t.region for t in tasks})
            - len({t.region for t in tasks if t.last_attempt_order}),
            current_region=next((t.region for t in tasks if t.state == "READY"), None),
        ),
    }
    return inventory


def run(db, job, payload, conditions, stopped):
    worker_id = job.worker_id
    while True:
        if stopped():
            return
        try:
            root, tasks, attempts = root_and_tasks(db, job, worker_id)
            for attempt in attempts:
                if attempt.state == "RESERVED":
                    task = next(t for t in tasks if t.id == attempt.task_id)
                    fail_attempt(
                        db, attempt, task, "INTERRUPTED_UNKNOWN", unknown=True, retryable=True
                    )
            inventory = summarize(db, job, root, tasks, attempts, conditions)
            reason = None
            if sum(v == "MATCH" for v in inventory.values()) >= payload["target_count"]:
                reason = "TARGET_REACHED"
            elif len(attempts) >= min(
                REQUEST_BUDGET, root.payload["query_plan"]["snapshot"]["request_budget"]
            ):
                reason = "REQUEST_BUDGET_REACHED"
            elif not any(t.state == "READY" for t in tasks):
                reason = (
                    "SOURCE_ERROR"
                    if any(t.state == "SOURCE_ERROR" for t in tasks)
                    else "QUERIES_EXHAUSTED"
                )
            if reason:
                summarize(db, job, root, tasks, attempts, conditions, reason)
                db.commit()
                return
            active_tasks = tasks
            if root.payload["query_plan"]["snapshot"].get("region_mode") == "prefecture_order":
                # Finish this prefecture (including delayed retries) before moving south.
                ready = [t for t in tasks if t.state == "READY"]
                region = min(ready, key=lambda t: t.query_order).region
                active_tasks = [t for t in ready if t.region == region]
            task = choose_task(active_tasks, datetime.now(timezone.utc))
            if task is None:
                db.commit()
                time.sleep(
                    0.2
                )  # Heartbeat/cancel checked every loop, no long lease-blocking sleep.
                continue
            collection = CollectionJob(
                project_id=job.project_id,
                operation_job_id=job.id,
                source="serper",
                keyword=task.keyword,
                region=task.region,
            )
            db.add(collection)
            db.flush()
            attempt = CollectionSearchAttempt(
                root_operation_id=root.id,
                task_id=task.id,
                operation_job_id=job.id,
                collection_job_id=collection.id,
                worker_id=worker_id,
                attempt_order=len(attempts) + 1,
                page=task.next_page,
            )
            db.add(attempt)
            db.flush()
            task.last_attempt_order = attempt.attempt_order
            summarize(db, job, root, tasks, [*attempts, attempt], conditions)
            db.commit()  # Reservation is durable BEFORE any HTTP or raw persistence.
            with capture_usage() as usage, capturing_discovery() as discovery:
                try:
                    candidates = search_serper_page(
                        task.keyword, task.region, PAGE_SIZE, attempt.page
                    )
                    error = None
                except ExternalServiceError as exc:
                    candidates, error = [], exc
            persist_discovery(db, collection, discovery)
            persist_usage(db, usage, job.project_id, collection_job_id=collection.id)
            if stopped():
                return  # Durable reservation is resolved as UNKNOWN on a future recovery.
            root_and_tasks(db, job, worker_id)  # Fence before accepting an old worker's response.
            db.refresh(attempt)
            if attempt.state != "RESERVED" or attempt.worker_id != worker_id:
                raise LostSearchLease()
            attempt.raw_count = discovery.received_count if discovery.response_received else None
            if error:
                fail_attempt(
                    db,
                    attempt,
                    task,
                    "SOURCE_ERROR",
                    retryable=error.retryable,
                    delay=error.retry_after,
                    message=error.public_message,
                )
                db.commit()
                continue
            before = target_collection.collection_inventory(db, job, conditions)

            def finish():
                after = target_collection.collection_inventory(db, job, conditions)
                growth = len(after.keys() - before.keys())
                attempt.state, attempt.new_candidate_count = "SUCCEEDED", growth
                attempt.finished_at = datetime.now(timezone.utc)
                successful_page(task, growth)
                collection.found_count = len(candidates)

            save_candidates(
                db,
                collection,
                target_collection.bounded_candidates(
                    db,
                    collection,
                    candidates,
                    payload["target_count"] - sum(v == "MATCH" for v in before.values()),
                ),
                task.keyword,
                before_commit=finish,
            )
            # Existing bounded optional presence enrichment remains separate from discovery.
            if payload.get("presence_search") and not stopped():
                collection.presence_search_plan = payload["presence_search"]
                db.commit()
                budget_job_id = db.scalar(
                    select(CollectionSearchAttempt.collection_job_id)
                    .where(
                        CollectionSearchAttempt.root_operation_id == root.id,
                    )
                    .order_by(CollectionSearchAttempt.attempt_order)
                    .limit(1)
                )
                extra_searches(
                    db,
                    collection,
                    PresenceSearchPlan.model_validate(payload["presence_search"]),
                    budget_job_id=budget_job_id,
                    stopped=stopped,
                    eligible=lambda company: (
                        not conditions
                        or target_collection.evaluate(db, company, conditions)["state"]
                        != "NO_MATCH"
                    ),
                )
        except LostSearchLease:
            db.rollback()
            return
