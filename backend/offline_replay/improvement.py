"""Development-only proposal input and entity-split comparison. No application/network imports."""

from collections import Counter
from copy import deepcopy
from typing import Any

from offline_replay.comparison import digest
from offline_replay.feedback import (
    PATTERNS,
    analyze,
    latest,
    metrics,
    normalize,
    projection,
    proposals,
)

VERSION = "improvement-workbench-v1"


def diagnostic_states(events):
    known = {"UNANALYZED", "READY", "REVIEW_REQUIRED", "BLOCKED", "STALE", "ERROR"}
    return dict(
        Counter(
            row["prediction"] if row["prediction"] in known else "UNKNOWN"
            for row in latest(events)
            if row["partition"] == "DEVELOPMENT"
            and not row["human"]
            and row["field"] == "form_analysis"
        )
    )


def plans(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    executable = {p["pattern"]: p for p in proposals(events)}
    result = []
    for pattern in analyze(events)["patterns"]:
        candidate = executable.get(pattern["pattern"])
        result.append(
            {
                "id": candidate["id"] if candidate else digest([VERSION, pattern["pattern"]]),
                **pattern,
                "feature": candidate["feature"] if candidate else None,
                "runner": "SAVED_CANDIDATE_PROJECTION" if candidate else "NOT_IMPLEMENTED",
                "requires_admin": True,
                "execution_allowed": False,
            }
        )
    errors = diagnostic_states(events).get("ERROR", 0)
    if errors:
        result.append(
            {
                "id": digest([VERSION, "FORM_DIAGNOSTIC_ERROR_OBSERVED"]),
                "pattern": "FORM_DIAGNOSTIC_ERROR_OBSERVED",
                "failed_samples": 0,
                "observed_diagnostic_errors": errors,
                "feature": None,
                "runner": "NOT_IMPLEMENTED",
                "requires_admin": True,
                "execution_allowed": False,
            }
        )
    return result


def packet(events: list[dict[str, Any]]) -> dict[str, Any]:
    # No evaluation counts, labels, IDs, evidence text or URLs go to a generator.
    return {
        "schema_version": VERSION,
        "development_analysis": analyze(events),
        "development_diagnostic_states": diagnostic_states(events),
        "allowed_proposals": plans(events),
        "instruction": (
            "Rank at most three allowed proposal IDs and explain hypotheses and limitations. "
            "Do not invent measured gains, costs or coverage. Do not write executable code, "
            "change rules, approve or deploy. All explanations are unverified hypotheses."
        ),
    }


def validate_advice(value: Any, request: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(value, dict) or set(value) != {"recommendations"}:
        raise ValueError("Invalid advice contract")
    rows = value["recommendations"]
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError("Advice limit exceeded")
    allowed = {row["id"] for row in request["allowed_proposals"]}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"proposal_id", "rationale", "limitation"}:
            raise ValueError("Unknown advice fields")
        if (
            not isinstance(row["proposal_id"], str)
            or row["proposal_id"] not in allowed
            or row["proposal_id"] in seen
        ):
            raise ValueError("Unknown or duplicate proposal")
        seen.add(row["proposal_id"])
        if any(
            not isinstance(row[k], str) or not 1 <= len(row[k]) <= 1200
            for k in ("rationale", "limitation")
        ):
            raise ValueError("Bounded explanatory text required")
    return deepcopy(rows)


def workbench(bundle: dict[str, Any], project_id: str, *, advice=None) -> dict[str, Any]:
    events = normalize(bundle, project_id)
    evaluation = [r for r in latest(events) if r["partition"] == "EVALUATION"]
    request = packet(events)
    candidates = request["allowed_proposals"]
    recommendations = validate_advice(advice, request) if advice is not None else []
    baseline = metrics(evaluation, None)
    comparisons = []
    for candidate in candidates:
        applicable = [
            r
            for r in evaluation
            if r["human"]
            and r["human_value"] is not None
            and r["prediction"] is not None
            and PATTERNS[r["field"]] == candidate["pattern"]
        ]
        eligible = [
            r
            for r in applicable
            if candidate["feature"] is not None
            and r["snapshot"].get("safety_blocked") is False
            and isinstance(r["snapshot"].get(candidate["feature"]), str)
            and r["snapshot"][candidate["feature"]].startswith("https://")
        ]
        runnable = candidate["feature"] is not None
        after = metrics(evaluation, candidate if runnable else None)
        changed = [r for r in eligible if projection(r, candidate) != r["prediction"]]
        comparisons.append(
            {
                "proposal": candidate,
                "status": "RUNNER_NOT_IMPLEMENTED"
                if not runnable
                else "NO_ELIGIBLE_EVALUATION"
                if not eligible
                else "EVALUATED",
                "evaluation_applicable_samples": len(applicable),
                "evaluation_eligible_samples": len(eligible),
                "changed_samples": len(changed),
                "improved_samples": sum(
                    projection(r, candidate) == r["human_value"] for r in changed
                ),
                "regressions": sum(
                    r["prediction"] == r["human_value"]
                    and projection(r, candidate) != r["human_value"]
                    for r in changed
                ),
                "before": baseline,
                "after": after,
                "adoption": "HUMAN_REVIEW_REQUIRED",
            }
        )
    return {
        "schema_version": VERSION,
        "dataset_kind": bundle["dataset_kind"],
        "input_hash": digest(bundle),
        "event_count": len(events),
        "development_analysis": request["development_analysis"],
        "development_diagnostic_states": request["development_diagnostic_states"],
        "baseline": baseline,
        "comparisons": comparisons,
        "recommendations": recommendations,
        "recommendation_truth": "UNVERIFIED_HYPOTHESIS",
        "identity_grouping": bundle.get("identity_grouping", "UNVERIFIED"),
        "sealed_evaluation_certified": False,
        "coverage": None,
        "human_review_seconds": None,
        "estimated_api_cost": None,
        "auto_adopt": False,
        "execution_allowed": False,
    }
