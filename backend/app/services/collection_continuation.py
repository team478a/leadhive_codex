"""Create a new bounded operation that resumes persisted query cursors."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OperationJob
from app.services.collection_query_plan import stamp_plan
from app.services.operations import add_operation_job

AUTO_CONTINUE_BUDGET_EXTENSION = 1000


def enqueue_continuation(
    db: Session, source: OperationJob, *, automatic: bool
) -> OperationJob | None:
    """Resume a completed, budget-limited collection without resetting its cursors."""
    if (source.payload or {}).get("source") == "google_places":
        return None
    progress = dict((source.payload or {}).get("collection_progress") or {})
    plan = (source.payload or {}).get("query_plan") or {}
    if (
        source.operation_type != "collect_search"
        or source.status != "completed"
        or progress.get("stop_reason") != "REQUEST_BUDGET_REACHED"
        or not plan.get("snapshot")
        or not progress.get("pending_queries")
    ):
        return None

    chain = dict((source.payload or {}).get("collection_chain") or {})
    total_requests = int(progress.get("total_requests", chain.get("total_requests", 0)))
    total_limit = int(
        chain.get("total_request_budget")
        or plan["snapshot"].get("total_request_budget")
        or plan["snapshot"].get("request_budget", 50)
    )
    original_auto_continue = bool(
        chain.get("auto_continue") or plan["snapshot"].get("auto_continue")
    )
    if automatic:
        remaining = total_limit - total_requests
    elif original_auto_continue:
        remaining = total_limit - total_requests
        if remaining <= 0:
            total_limit = total_requests + AUTO_CONTINUE_BUDGET_EXTENSION
            remaining = AUTO_CONTINUE_BUDGET_EXTENSION
        automatic = True
    else:
        remaining = 50
    if remaining <= 0:
        return None

    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == source.project_id,
            OperationJob.operation_type == "collect_search",
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        return None

    root_ids = list(dict.fromkeys([*(chain.get("root_ids") or []), str(source.id)]))
    payload = dict(source.payload or {})
    payload.pop("query_plan", None)
    payload.pop("collection_progress", None)
    payload["resume_from_root_id"] = str(source.id)
    payload["segment_request_limit"] = min(50, remaining)
    payload["auto_continue"] = automatic
    payload["search_request_limit"] = total_limit if automatic else 50
    payload["collection_chain"] = dict(
        root_ids=root_ids,
        total_requests=total_requests,
        total_request_budget=total_limit if automatic else total_requests + 50,
        auto_continue=automatic,
        continuation_count=int(chain.get("continuation_count", 0)) + 1,
    )
    job = OperationJob(
        project_id=source.project_id,
        operation_type="collect_search",
        payload=payload,
    )
    if not add_operation_job(db, job):
        return None
    stamp_plan(job)
    db.flush()
    job.payload = {
        **job.payload,
        "collection_progress": {
            **progress,
            "requests": 0,
            "total_requests": total_requests,
            "request_budget": min(50, remaining),
            "total_request_budget": total_limit if automatic else total_requests + 50,
            "stop_reason": None,
            "continuation_count": payload["collection_chain"]["continuation_count"],
            "operation_ids": root_ids,
            "continued_from": str(source.id),
        },
    }
    return job
