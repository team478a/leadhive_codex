"""Versioned, immutable plans. Only new, explicitly enabled jobs receive a plan."""

import hashlib
import json

from app.config import settings
from app.services.collection_search_policy import (
    MAX_PAGE_ATTEMPTS,
    MAX_PAGES,
    PAGE_SIZE,
    REQUEST_BUDGET,
    STAGNANT_PAGES,
    VERSION,
)


def plan_snapshot(payload):
    return {
        "version": VERSION,
        "keywords": list(dict.fromkeys(payload["keywords"])),
        "region": payload["region"],
        "target_count": payload["target_count"],
        "condition_binding": payload.get("condition_binding"),
        "presence_search": payload.get("presence_search"),
        "request_budget": min(
            REQUEST_BUDGET, payload.get("search_request_limit") or REQUEST_BUDGET
        ),
        "page_size": PAGE_SIZE,
        "max_pages": MAX_PAGES,
        "max_page_attempts": MAX_PAGE_ATTEMPTS,
        "stagnant_pages": STAGNANT_PAGES,
    }


def plan_hash(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stamp_plan(job):
    if (
        settings.collection_fair_scheduler_enabled
        and job.operation_type == "collect_search"
        and job.payload.get("target_count")
        and job.payload.get("source") == "serper"
    ):
        snapshot = plan_snapshot(job.payload)
        job.payload = {
            **job.payload,
            "query_plan": {
                "root_operation_id": str(job.id),
                "hash": plan_hash(snapshot),
                "snapshot": snapshot,
            },
        }
