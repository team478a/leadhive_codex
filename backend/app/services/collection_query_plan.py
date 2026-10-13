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
    snapshot = {
        "version": VERSION,
        "keywords": list(dict.fromkeys(payload["keywords"])),
        "region": payload["region"],
        "target_count": payload["target_count"],
        "condition_binding": payload.get("condition_binding"),
        "presence_search": payload.get("presence_search"),
        "request_budget": min(
            REQUEST_BUDGET,
            payload.get("segment_request_limit")
            or payload.get("search_request_limit")
            or REQUEST_BUDGET,
        ),
        "page_size": PAGE_SIZE,
        "max_pages": MAX_PAGES,
        "max_page_attempts": MAX_PAGE_ATTEMPTS,
        "stagnant_pages": STAGNANT_PAGES,
    }
    if payload.get("auto_continue"):
        snapshot["auto_continue"] = True
        snapshot["total_request_budget"] = payload.get("search_request_limit") or REQUEST_BUDGET
    # Omit the default so hashes of existing jobs remain unchanged.
    if payload.get("region_mode") == "prefecture_order":
        snapshot["region_mode"] = "prefecture_order"
        from app.services.scraper import PREFECTURES

        parts = [part.strip() for part in payload["region"].split("/")]
        if len(parts) > 1 and all(part in PREFECTURES for part in parts):
            snapshot["selected_prefectures"] = [area for area in PREFECTURES if area in parts]
    return snapshot


def planned_queries(snapshot):
    from app.services.scraper import PREFECTURES

    regions = (
        PREFECTURES
        if snapshot.get("region_mode") == "prefecture_order" and snapshot["region"] == "全国"
        else (snapshot["region"],)
    )
    if snapshot.get("region_mode") == "prefecture_order" and snapshot.get("selected_prefectures"):
        regions = tuple(snapshot["selected_prefectures"])
    return [(keyword, region) for region in regions for keyword in snapshot["keywords"]]


def plan_hash(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stamp_plan(job):
    if (
        (
            settings.collection_fair_scheduler_enabled
            or job.payload.get("region_mode") == "prefecture_order"
        )
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
