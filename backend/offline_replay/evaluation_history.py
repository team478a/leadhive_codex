"""Write-once evaluation checkpoints; observed trends are never causal proof."""

from datetime import datetime, timezone
from typing import Any

from offline_replay.comparison import digest
from offline_replay.feedback import VERSION as FEEDBACK_VERSION
from offline_replay.feedback import latest, metrics, normalize, timestamp

VERSION = "evaluation-history-v1"
RATES = (
    "collection_precision",
    "official_site_accuracy",
    "contact_discovery_rate",
    "misclassification_rate",
)
REASONS = {
    "INSUFFICIENT_EVALUATION",
    "COHORT_CHANGED",
    "NO_MEASURED_GAIN",
    "REGRESSION",
    "NOT_APPLIED",
    "OTHER",
}


def checkpoint(bundle: dict[str, Any], project_id: str, *, start: str, end: str) -> dict[str, Any]:
    """Select reviews in [start,end), then freeze their aggregate and provenance."""
    begin = datetime.fromisoformat(timestamp(start).replace("Z", "+00:00"))
    finish = datetime.fromisoformat(timestamp(end).replace("Z", "+00:00"))
    if begin >= finish:
        raise ValueError("Positive evaluation interval required")
    events = normalize(bundle, project_id)
    selected = [r for r in events if begin <= datetime.fromisoformat(r["observed_at"]) < finish]
    evaluation = [r for r in latest(selected) if r["partition"] == "EVALUATION"]
    # Hashes include Human labels and original predictions; no URLs/identifiers exported.
    samples = [
        [r["entity_key"], r["field"], r["snapshot_hash"], r["human_value"], r["human"]]
        for r in evaluation
    ]
    versions = sorted({digest(r["versions"]) for r in evaluation})
    result = {
        "schema_version": VERSION,
        "metric_definition": FEEDBACK_VERSION,
        "project_hash": digest(project_id),
        "dataset_kind": bundle["dataset_kind"],
        "input_hash": digest(bundle),
        "period": {"start_inclusive": begin.isoformat(), "end_exclusive": finish.isoformat()},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "review_events": len(selected),
        "evaluation_samples": len(evaluation),
        "unresolved_samples": sum(
            r["human"] and (r["human_value"] is None or r["prediction"] is None) for r in evaluation
        ),
        "cohort_hash": digest(sorted(samples, key=digest)),
        "version_hashes": versions,
        "versions_complete": bool(evaluation)
        and all(all(v is not None for v in r["versions"].values()) for r in evaluation),
        "metrics": metrics(evaluation, None),
        "coverage": None,
        "human_review_seconds": None,
        "runtime_applied": False,
        "sealed_evaluation_certified": False,
        "execution_allowed": False,
    }
    result["checkpoint_hash"] = digest(result)
    return result


def validate(value: dict[str, Any]) -> None:
    if value.get("schema_version") != VERSION or value.get("checkpoint_hash") != digest(
        {k: v for k, v in value.items() if k != "checkpoint_hash"}
    ):
        raise ValueError("Invalid checkpoint integrity")
    if value.get("metric_definition") != FEEDBACK_VERSION:
        raise ValueError("Unsupported metric definition")


def trend(before: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    validate(before)
    validate(current)
    if before["project_hash"] != current["project_hash"]:
        raise ValueError("Cross-project comparison refused")
    reasons = ["NOT_APPLIED", "EVALUATION_NOT_SEALED"]
    if before["dataset_kind"] != current["dataset_kind"]:
        reasons.append("DATASET_KIND_CHANGED")
    if before["cohort_hash"] != current["cohort_hash"]:
        reasons.append("COHORT_CHANGED")
    if not before["versions_complete"] or not current["versions_complete"]:
        reasons.append("VERSION_UNKNOWN")
    deltas = {}
    for name in RATES:
        old, new = before["metrics"][name], current["metrics"][name]
        deltas[name] = new - old if old is not None and new is not None else None
    if not any(v is not None for v in deltas.values()):
        reasons.append("INSUFFICIENT_EVALUATION")
    return {
        "schema_version": VERSION,
        "before_hash": before["checkpoint_hash"],
        "current_hash": current["checkpoint_hash"],
        "before": before["metrics"],
        "current": current["metrics"],
        "observed_deltas": deltas,
        "limitations": reasons,
        "improvement_demonstrated": False,
        "execution_allowed": False,
    }


def observation(report: dict[str, Any], *, reviewer: str, reason: str, note: str) -> dict[str, Any]:
    """Separate operator explanation; the offline CLI cannot authenticate a Human."""
    if reason not in REASONS or not reviewer.strip() or not 1 <= len(note.strip()) <= 2000:
        raise ValueError("Reviewer, supported reason and bounded note required")
    return {
        "schema_version": VERSION,
        "comparison_hash": digest(report),
        "reviewer_claim": reviewer,
        "principal_verified": False,
        "reason": reason,
        "note": note.strip(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "classification": "UNVERIFIED_OPERATOR_EXPLANATION",
        "execution_allowed": False,
    }
