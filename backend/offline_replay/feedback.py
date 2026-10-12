"""Phase 5 isolated feedback lab. No application imports, DB, AI calls or execution hooks."""

from collections import Counter
from datetime import datetime
from typing import Any

from offline_replay.comparison import digest

VERSION = "feedback-lab-v1"
FIELDS = {"target", "official_url", "contact_url", "discovery", "form_analysis"}
PATTERNS = {
    "official_url": "OFFICIAL_SITE_MISIDENTIFIED",
    "target": "INDUSTRY_MISCLASSIFIED",
    "discovery": "CANDIDATE_MISSED",
    "contact_url": "CONTACT_URL_MISIDENTIFIED",
    "form_analysis": "FORM_ANALYSIS_FAILED",
}
REASONS = {
    "confirmed",
    "wrong_company",
    "wrong_industry",
    "article",
    "recruitment",
    "reservation",
    "broken_link",
    "wrong_destination",
    "other",
    "diagnostic",
}


def partition(entity_key: str) -> str:
    """Frozen entity-level split; corrections, duplicate queries and fields stay together."""
    return "EVALUATION" if int(digest(entity_key)[:8], 16) % 5 == 0 else "DEVELOPMENT"


def timestamp(value: Any) -> str:
    if (
        not isinstance(value, str)
        or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None
    ):
        raise ValueError("Timezone-bound timestamp required")
    return value


def normalize(bundle: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    """Portable export contract. Do not infer missing historic predictions/versions."""
    if bundle.get("schema_version") != VERSION or bundle.get("dataset_kind") not in {
        "SYNTHETIC",
        "AUTHORIZED_EXPORT",
    }:
        raise ValueError("Unsupported dataset")
    records = bundle.get("records")
    if not isinstance(records, list) or len(records) > 10000 or not project_id:
        raise ValueError("Invalid project or record limit")
    result = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid export record")
        if record.get("project_id") != project_id:
            raise ValueError("Cross-project export refused")
        source = record.get("source")
        if source not in {
            "collection_activity",
            "raw_human_review",
            "form_diagnostic",
            "site_identity_review",
        }:
            raise ValueError("Unsupported source")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Payload required")
        entity = record.get("entity_key")
        record_id = record.get("source_id")
        if (
            not isinstance(entity, str)
            or not entity
            or not isinstance(record_id, str)
            or not record_id
        ):
            raise ValueError("Stable export identities required")
        identity = (source, record_id)
        if identity in seen:
            raise ValueError("Duplicate source event")
        seen.add(identity)
        field = record.get("field")
        before = record.get("prediction")  # Captured at decision time, never current Company.
        human_value = None
        human = False
        reason: Any = "diagnostic"
        actor = None
        if source == "collection_activity":
            field = "contact_url" if payload.get("subject") == "contact_url" else "target"
            if payload.get("subject") not in {"company", "contact_url"}:
                raise ValueError("Invalid Activity subject")
            outcome = payload.get("outcome")
            if outcome not in {"OK", "NG", "CORRECTED"} or (
                field == "target" and outcome == "CORRECTED"
            ):
                raise ValueError("Invalid Activity outcome")
            actor = payload.get("actor_user_id")
            human = True
            reason = payload.get("reason")
            if field == "contact_url":
                before = payload.get("before_contact_url")
                # NG invalidates the old URL; it does NOT mean no valid destination exists.
                human_value = payload.get("after_contact_url") if outcome != "NG" else None
            else:
                human_value = outcome == "OK"
        elif source == "raw_human_review":
            actor = payload.get("reviewer_id")
            human = True
            outcome = payload.get("outcome")
            valid = {
                "CORRECT",
                "WRONG_INDUSTRY",
                "WRONG_AREA",
                "DUPLICATE",
                "WRONG_ENTITY",
                "PORTAL_OR_AGGREGATOR",
                "CLOSED_OR_INACTIVE",
                "UNCERTAIN",
                "OTHER",
            }
            if outcome not in valid or field != "target":
                raise ValueError("Invalid Raw review")
            human_value = (
                True
                if outcome == "CORRECT"
                else False
                if outcome not in {"UNCERTAIN", "OTHER"}
                else None
            )
            reason = "wrong_industry" if outcome == "WRONG_INDUSTRY" else "other"
        elif source == "site_identity_review":
            field = "official_url"
            actor = payload.get("actor_user_id")
            human = True
            outcome = payload.get("event_type")
            if outcome not in {"CONFIRMED", "REVOKED"}:
                raise ValueError("Invalid site identity event")
            # The export must supply the reviewed official root, not the evidence subpage.
            human_value = record.get("reviewed_official_url") if outcome == "CONFIRMED" else None
            reason = "confirmed" if outcome == "CONFIRMED" else "other"
        else:
            outcome = "OBSERVED"
            if field != "form_analysis":
                raise ValueError("Diagnostic field required")
        if field not in FIELDS or (
            human
            and (not isinstance(actor, str) or not actor or record.get("principal") != "HUMAN")
        ):
            raise ValueError("Human provenance required; Agent/System cannot label")
        if field in {"target", "discovery"}:
            if any(v is not None and type(v) is not bool for v in (before, human_value)):
                raise ValueError("Boolean judgment required")
        elif any(v is not None and not isinstance(v, str) for v in (before, human_value)):
            raise ValueError("Text judgment required")
        if reason not in REASONS:
            raise ValueError("Unsupported reason")
        expected_hash = record.get("snapshot_hash")
        snapshot = record.get("snapshot")
        if not isinstance(snapshot, dict) or expected_hash != digest(snapshot):
            raise ValueError("Frozen snapshot hash mismatch")
        captured_at = timestamp(record.get("snapshot_observed_at"))
        reviewed_at = timestamp(record.get("observed_at"))
        if datetime.fromisoformat(captured_at) > datetime.fromisoformat(reviewed_at):
            raise ValueError("Post-review snapshot cannot be replay input")
        versions = record.get("versions") or {}
        if not isinstance(versions, dict):
            raise ValueError("Invalid version metadata")
        # Diagnostics and Human corrections remain distinct even when initiated by a Human.
        result.append(
            {
                "event_key": digest(identity),
                "project_id": project_id,
                "company_id": record.get("company_id"),
                "entity_key": entity,
                "field": field,
                "prediction": before,
                "human_value": human_value,
                "human": human,
                "actor": actor,
                "outcome": outcome,
                "reason": reason,
                "evidence": payload.get("evidence_url")
                or payload.get("note")
                or record.get("evidence_reference"),
                "observed_at": reviewed_at,
                "versions": {key: versions.get(key) for key in ("model", "prompt", "rule", "code")},
                "source": source,
                "snapshot_hash": expected_hash,
                "snapshot": snapshot,
                "partition": partition(entity),
            }
        )
    return result


def latest(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest review per frozen sample; conflicting timestamps fail rather than cherry-pick."""
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        key = (event["entity_key"], event["field"], event["snapshot_hash"])
        old = rows.get(key)
        if old and datetime.fromisoformat(event["observed_at"]) == datetime.fromisoformat(
            old["observed_at"]
        ):
            raise ValueError("Ambiguous same-time feedback")
        if not old or datetime.fromisoformat(event["observed_at"]) > datetime.fromisoformat(
            old["observed_at"]
        ):
            rows[key] = event
    return list(rows.values())


def analyze(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Only development feedback may influence suggestions; diagnostics are not truth."""
    failures: Counter[str] = Counter()
    affected: dict[str, set[str]] = {}
    diagnostic_count = 0
    unresolved = 0
    for row in latest(events):
        if row["partition"] != "DEVELOPMENT":
            continue
        if not row["human"]:
            diagnostic_count += 1
            continue
        rejected_url = (
            row["field"] == "contact_url" and row["outcome"] == "NG" and bool(row["prediction"])
        )
        if (row["human_value"] is None and not rejected_url) or row["prediction"] is None:
            unresolved += 1
            continue
        if rejected_url or row["prediction"] != row["human_value"]:
            pattern = PATTERNS[row["field"]]
            if row["field"] == "target" and row["reason"] != "wrong_industry":
                pattern = "TARGET_MISCLASSIFIED_UNSPECIFIED"
            failures[pattern] += 1
            affected.setdefault(pattern, set()).add(row["entity_key"])
    return {
        "patterns": [
            {"pattern": p, "failed_samples": n, "affected_entities": len(affected[p])}
            for p, n in failures.most_common()
        ],
        "unresolved_samples": unresolved,
        "diagnostics_not_human_truth": diagnostic_count,
    }


def proposals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic proposal scaffold, NOT AI-generated code or deployable configuration."""
    patterns = {row["pattern"] for row in analyze(events)["patterns"]}
    choices = [
        ("CONTACT_URL_MISIDENTIFIED", "saved_contact_candidate"),
        ("OFFICIAL_SITE_MISIDENTIFIED", "saved_official_candidate"),
    ]
    return [
        {
            "id": digest([VERSION, pattern, feature]),
            "generator": "DETERMINISTIC_POC",
            "pattern": pattern,
            "feature": feature,
            "status": "PROPOSED",
            "requires_admin": True,
            "execution_allowed": False,
        }
        for pattern, feature in choices
        if pattern in patterns
    ]


def suggestion_packet(events: list[dict[str, Any]]) -> dict[str, Any]:
    """AI-ready aggregate input. No evaluation labels, company text or free-form executable code."""
    return {
        "schema_version": VERSION,
        "instruction": (
            "Rank the allowlisted proposal IDs using development aggregates only. "
            "Explain uncertainty. Do not invent metrics, write code, approve, or apply rules."
        ),
        "development_analysis": analyze(events),
        "allowed_proposals": proposals(events),
        "response_contract": {"proposal_id": "allowlisted ID", "rationale": "non-executable text"},
    }


def projection(row: dict[str, Any], candidate: dict[str, Any] | None) -> Any:
    """Saved, pre-review extraction candidates only. Never reads corrected Human values."""
    before = row["prediction"]
    if not candidate or PATTERNS[row["field"]] != candidate["pattern"]:
        return before
    snapshot = row["snapshot"]
    if snapshot.get("safety_blocked") is not False:
        return before
    value = snapshot.get(candidate["feature"])
    return value if isinstance(value, str) and value.startswith("https://") else before


def metrics(rows: list[dict[str, Any]], candidate: dict[str, Any] | None) -> dict[str, Any]:
    judged = [r for r in rows if r["human"] and r["human_value"] is not None]
    paired = [r for r in judged if r["prediction"] is not None]

    def ratio(n: int, d: int) -> float | None:
        return n / d if d else None

    counts = {}
    for field in FIELDS:
        values = [r for r in paired if r["field"] == field]
        counts[field] = {
            "evaluated": len(values),
            "exact_matches": sum(projection(r, candidate) == r["human_value"] for r in values),
        }
    targets = [r for r in paired if r["field"] == "target" and projection(r, candidate) is True]
    contacts = [r for r in paired if r["field"] == "contact_url" and r["human_value"]]
    return {
        "counts": counts,
        "judged_samples": len(judged),
        "paired_samples": len(paired),
        "collection_precision": ratio(sum(r["human_value"] is True for r in targets), len(targets)),
        "official_site_accuracy": ratio(
            counts["official_url"]["exact_matches"], counts["official_url"]["evaluated"]
        ),
        "contact_discovery_rate": ratio(
            sum(projection(r, candidate) == r["human_value"] for r in contacts), len(contacts)
        ),
        "misclassification_rate": ratio(
            sum(projection(r, candidate) != r["human_value"] for r in paired), len(paired)
        ),
        "production_processing_seconds": None,
        "api_cost": None,
    }


def compare(bundle: dict[str, Any], project_id: str) -> dict[str, Any]:
    events = normalize(bundle, project_id)
    evaluation = [r for r in latest(events) if r["partition"] == "EVALUATION"]
    candidates = proposals(events)
    baseline = metrics(evaluation, None)
    comparisons = []
    for candidate in candidates:
        after = metrics(evaluation, candidate)
        regressions = sum(
            r["human"]
            and r["human_value"] is not None
            and r["prediction"] is not None
            and r["prediction"] == r["human_value"]
            and projection(r, candidate) != r["human_value"]
            for r in evaluation
        )
        comparisons.append(
            {
                "proposal": candidate,
                "before": baseline,
                "after": after,
                "regressions": regressions,
                "adoption": "HUMAN_REVIEW_REQUIRED",
            }
        )
    return {
        "schema_version": VERSION,
        "dataset_kind": bundle["dataset_kind"],
        "input_hash": digest(bundle),
        "event_count": len(events),
        "development_entities": len(
            {r["entity_key"] for r in events if r["partition"] == "DEVELOPMENT"}
        ),
        "evaluation_entities": len(
            {r["entity_key"] for r in events if r["partition"] == "EVALUATION"}
        ),
        "unknown_version_events": sum(
            any(v is None for v in r["versions"].values()) for r in events
        ),
        "analysis": analyze(events),
        "comparisons": comparisons,
        "baseline": baseline,
        "execution_allowed": False,
        "auto_adopt": False,
    }
