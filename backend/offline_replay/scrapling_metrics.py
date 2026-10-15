"""Aggregate only. Availability and disagreement are never Human accuracy."""

import re
import statistics
from collections import Counter

FIELDS = (
    "company_name",
    "address",
    "phone",
    "contact_url",
    "instagram_url",
    "x_url",
    "facebook_url",
    "youtube_url",
    "tiktok_url",
    "line_url",
)
METHODS = ("current", "scrapling_static", "scrapling_dynamic_replay")


def normalized(field: str, value: str) -> str:
    if field == "phone":
        return re.sub(r"[^0-9]", "", value)
    return value.strip()


def summarize(rows: list[dict]) -> dict:
    count = len(rows)
    methods = {}
    for method in METHODS:
        entries = [row["methods"].get(method, {}) for row in rows]
        successful = [entry for entry in entries if entry.get("success") is True]
        times = [
            entry["elapsed_seconds"]
            for entry in entries
            if isinstance(entry.get("elapsed_seconds"), (int, float))
        ]
        accuracy = {}
        for field in FIELDS:
            labeled = [
                (row.get("truth", {}).get(field), entry)
                for row, entry in zip(rows, entries)
                if row.get("truth", {}).get("human_verified") is True
                and row.get("truth", {}).get("reviewer")
                and row.get("truth", {}).get("reviewed_at")
                and field in row.get("truth", {})
                and isinstance(row["truth"][field], str)
            ]
            correct = sum(
                entry.get("success") is True
                and normalized(field, expected)
                == normalized(field, entry.get("fields", {}).get(field, ""))
                for expected, entry in labeled
            )
            accuracy[field] = {
                "reviewed": len(labeled),
                "correct": correct if labeled else None,
                "accuracy": correct / len(labeled) if labeled else None,
            }
        methods[method] = {
            "html_acquired": sum(row.get("html_acquired") is True for row in rows),
            "extraction_success": len(successful),
            "success_rate": len(successful) / count if count else None,
            "field_availability": {
                field: sum(bool(entry.get("fields", {}).get(field)) for entry in successful)
                / len(successful)
                if successful
                else None
                for field in FIELDS
            },
            "human_accuracy": accuracy,
            "mean_processing_seconds": statistics.mean(times) if times else None,
            "estimated_cost_per_company": None,
            "failure_reasons": dict(
                Counter(
                    entry.get("reason", "UNKNOWN") for entry in entries if not entry.get("success")
                )
            ),
        }
    changed = {}
    for method in METHODS[1:]:
        changed[method] = {
            field: sum(
                row["methods"].get(method, {}).get("success") is True
                and row["methods"].get("current", {}).get("success") is True
                and row["methods"][method]["fields"].get(field, "")
                != row["methods"]["current"]["fields"].get(field, "")
                for row in rows
            )
            for field in FIELDS
        }
    return {
        "cohort_size": count,
        "methods": methods,
        "field_disagreements": changed,
        "correct_sales_target_information_companies": None,
        "js_correctness_improvement_companies": None,
        "misextractions": None,
        "misclassifications": None,
        "acquisition_failure_reasons": dict(
            Counter(
                row.get("acquisition_reason", "UNKNOWN")
                for row in rows
                if not row.get("html_acquired")
            )
        ),
        "external_gets": sum(row.get("external_gets", 0) for row in rows),
        "estimated_processing_cost": None,
        "search_api_calls": 0,
        "ai_calls": 0,
        "db_writes": 0,
        "email_sent": 0,
        "form_post": 0,
        "approvals": 0,
    }
