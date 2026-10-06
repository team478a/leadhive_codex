"""Aggregate only; no identifiers or contact values leave this summary."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.models import LeadProcessingUsage, LeadReviewSession
from app.services.benchmark_evidence import DEFINITION, EXTRA, STAGES, details
from app.services.sendability import REASONS

RESULTS = Path(__file__).resolve().parents[3] / "docs" / "results"
BUNDLE = Path(__file__).resolve().parents[1] / "benchmark_baselines.json"


def baseline_for(cohort_hash):
    try:
        manifest = json.loads(
            (RESULTS / "lead-completion-benchmark-2026-10-07.json").read_text(encoding="utf-8")
        )
        if manifest.get("cohort_hash") != cohort_hash:
            return None
        return json.loads(
            (RESULTS / "lead-completion-baseline-2026-10-06.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, AttributeError):
        # Container/installed packages do not carry repository docs. Only the
        # aggregate catalog is bundled, never membership or private snapshots.
        try:
            return json.loads(BUNDLE.read_text(encoding="utf-8")).get(cohort_hash)
        except (OSError, ValueError, AttributeError):
            return None


def costs(db, cohort, project):
    usage = db.scalars(
        select(LeadProcessingUsage).where(
            LeadProcessingUsage.project_id == project.id,
            LeadProcessingUsage.started_at >= cohort.created_at,
        )
    ).all()
    reviews = db.scalars(
        select(LeadReviewSession).where(
            LeadReviewSession.cohort_id == cohort.id,
        )
    ).all()
    tokens = [u for u in usage if u.kind == "ai"]
    timed = [r.duration_seconds for r in reviews if r.duration_seconds is not None]
    priced = bool(usage) and all(
        u.estimated_cost is not None and u.currency and u.pricing_version for u in usage
    )
    same_currency = len({u.currency for u in usage}) == 1
    return dict(
        coverage="RECORDED_PROJECT_USAGE_SINCE_COHORT_CREATION_NOT_TOTAL_COST",
        observed_search_calls=dict(Counter(u.provider for u in usage if u.kind == "search")),
        search_calls=None,
        places_calls=None,
        ai_calls=None,
        observed_ai_calls=len(tokens),
        input_tokens=sum(u.input_tokens for u in tokens)
        if tokens and all(u.input_tokens is not None for u in tokens)
        else None,
        output_tokens=sum(u.output_tokens for u in tokens)
        if tokens and all(u.output_tokens is not None for u in tokens)
        else None,
        estimated_cost=float(sum(u.estimated_cost for u in usage))
        if priced and same_currency
        else None,
        currency=usage[0].currency if priced and same_currency else None,
        cost_per_dm_ready=None,
        human_review_seconds=sum(timed) if timed else None,
        review_sessions=len(reviews),
        completed_reviews=sum(r.finished_at is not None for r in reviews),
        unmeasured_reviews=sum(r.duration_seconds is None for r in reviews),
        category_timing_available=False,
    )


def summarize(rows, discovered, metadata, *, complete=True):
    stages: list[dict[str, Any]] = []
    for code in STAGES:
        raw = [r["benchmark"]["raw_stages"][code] for r in rows]
        passed = [r["benchmark"]["passed_stages"][code] for r in rows]
        stages.append(
            dict(
                code=code,
                observed_count=sum(v is True for v in raw),
                unknown=sum(v is None for v in raw),
                passed_count=sum(v is True for v in passed),
                passed_unknown=sum(v is None for v in passed),
            )
        )
    for index, stage in enumerate(stages):
        previous = stages[index - 1] if index else None
        stage["from_discovered"] = (
            round(100 * stage["observed_count"] / discovered, 2)
            if complete and discovered and not stage["unknown"]
            else None
        )
        stage["conversion_rate"] = (
            round(100 * stage["passed_count"] / previous["passed_count"], 2)
            if complete
            and previous
            and previous["passed_count"]
            and not stage["passed_unknown"]
            and not previous["passed_unknown"]
            else None
        )
    reason_counts = Counter(c for r in rows for c in set(r["benchmark"]["reason_codes"]))
    primary = Counter(
        r["benchmark"]["primary_reason"] for r in rows if r["benchmark"]["primary_reason"]
    )
    sole = Counter(c for r in rows for c in r["benchmark"]["sole_blockers"])
    unlock = Counter(c for r in rows for c in r["benchmark"]["potential_unlock"])
    bottlenecks = [
        dict(
            **details(code),
            affected_leads=count,
            primary_leads=primary[code],
            sole_blocker_leads=sole[code],
            potential_unlock=unlock[code],
        )
        for code, count in reason_counts.items()
    ]
    bottlenecks.sort(key=lambda r: (-r["potential_unlock"], -r["affected_leads"], r["code"]))
    destinations: dict[str, Any] = {}
    for row in rows:
        for d in row["destinations"]:
            previous = destinations.get(d["key"], dict(leads=0, shared=False, type=d["type"]))
            destinations[d["key"]] = dict(
                leads=previous["leads"] + 1,
                shared=previous["shared"] or d["shared"],
                type=d["type"],
            )
    dm_ready = sum(r["dm_ready"] for r in rows)
    cost = {
        **metadata["cost"],
        "cost_per_dm_ready": metadata["cost"]["estimated_cost"] / dm_ready
        if complete
        and dm_ready
        and metadata["cost"].get("estimated_cost") is not None
        and metadata["cost"].get("coverage") == "COMPLETE_COHORT"
        else None,
    }
    categories = {
        "official_site": {"OFFICIAL_SITE_NOT_FOUND"},
        "identity": {"IDENTITY_UNCERTAIN"},
        "destination_purpose": {"DESTINATION_PURPOSE_UNCERTAIN"},
        "shared_destination": {"SHARED_DESTINATION"},
        "form": {
            "CAPTCHA",
            "FORM_NOT_READY",
            "FORM_UNANALYZED",
            "FORM_ANALYSIS_STALE",
            "REQUIRED_FIELD_UNKNOWN",
            "FORM_TECHNICALLY_UNSUPPORTED",
        },
        "dm_evidence": {
            "DM_NOT_PREPARED",
            "DM_PREPARATION_EXPIRED",
            "DM_PREPARATION_INVALIDATED",
            "DM_REVIEW_REQUIRED",
        },
    }
    return dict(
        definition=DEFINITION,
        discovered=discovered,
        inspected=len(rows),
        complete=complete,
        stages=stages,
        distributions={
            field: dict(Counter(r["benchmark"][field] for r in rows))
            for field in ["match", "identity", "official_site", "permission", "preparation"]
        },
        sendability=dict(Counter(r["status"] for r in rows)),
        dm_ready=dm_ready,
        dm_ready_rate=round(dm_ready / discovered * 100, 2) if complete and discovered else None,
        destinations=dict(
            leads=sum(bool(r["destinations"]) for r in rows),
            total=sum(len(r["destinations"]) for r in rows),
            unique=len(destinations),
            shared=sum(d["shared"] or d["leads"] > 1 for d in destinations.values()),
            by_type={
                kind: sum(d["type"] == kind for d in destinations.values())
                for kind in ("email", "form")
            },
        ),
        bottlenecks=bottlenecks,
        reason_counts={c: reason_counts[c] for c in sorted(REASONS | EXTRA)},
        primary_reason_counts=dict(primary),
        cost=cost,
        human_work_queue={
            k: sum(
                r["status"] != "BLOCKED" and bool(set(r["benchmark"]["reason_codes"]) & codes)
                for r in rows
            )
            for k, codes in categories.items()
        },
        human_review_required_leads=sum(
            r["status"] != "BLOCKED" and bool(r["benchmark"]["reason_codes"]) for r in rows
        ),
        human_queue_blocked_excluded=sum(r["status"] == "BLOCKED" for r in rows),
        potential_unlock_definition=(
            "CONDITIONAL_SINGLE_RECORDED_PREPARATION_GATE_NOT_PREDICTED_GAIN_OR_SEND_PERMISSION; "
            "upstream MATCHED unknown is not solved"
        ),
        uninstrumented_reasons={
            "ROBOTS_BLOCKED": None,
            "JS_FORM_UNSUPPORTED": None,
            "CONFIRMATION_FORM_UNSUPPORTED": None,
            "SENDER_NOT_READY": None,
        },
        reason_aliases={
            "CORE_PERMISSION_BLOCKED": "use specific DO_NOT_CONTACT/SUPPRESSED/SALES_PROHIBITED",
            "FORM_REVIEW_REQUIRED": "FORM_NOT_READY",
            "JS_FORM_UNSUPPORTED": "FORM_TECHNICALLY_UNSUPPORTED (JS subtype not instrumented)",
        },
        execution_allowed=False,
    )
