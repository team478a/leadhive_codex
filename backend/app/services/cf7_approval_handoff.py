"""Inert preparation boundary for future Human approval; not an authorization."""

from copy import deepcopy

from app.services.cf7_candidate_contract import digest
from app.services.cf7_real_contract_preview import preview
from app.services.cf7_real_encoding import encode, summarize
from app.services.form_execution_plan import PlanError

DEFINITION = "real-cf7-human-handoff-preview-v1"


def prepare(report: dict, observation: dict | None) -> dict:
    """Rebuild from authorized server records. No DB write, request or dispatch."""
    current = preview(report, observation)
    result = {
        "status": "HOLD",
        "reasons": current["reasons"],
        "snapshot": None,
        "snapshot_hash": None,
        "authorization_type": None,
        "execution_allowed": False,
        "eligible_for_approval": False,
        "approval_request_created": False,
        "live_fetch_performed": False,
    }
    if current["status"] != "PREVIEW_ONLY":
        return result
    try:
        encoding = summarize(
            encode(report, observation, expected_contract_hash=current["contract_hash"])
        )
    except PlanError:
        result["reasons"] = ["WIRE_ENCODING_UNSUPPORTED"]
        return result
    snapshot = {
        "definition_version": DEFINITION,
        "source_kind": "REAL_SITE_STATIC_HTML",
        "contract": deepcopy(current["contract"]),
        "contract_hash": current["contract_hash"],
        "encoding": encoding,
        "input_review": {
            "actor_user_id": report["reviewed_by"],
            "reviewed_at": str(report["reviewed_at"]),
            "expires_at": str(report["review_expires_at"]),
            "snapshot_hash": report["snapshot_hash"],
        },
        "expires_at": current["contract"]["expires_at"],
        "authorization_type": None,
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
    result.update(status="PREPARATION_ONLY", snapshot=snapshot, snapshot_hash=digest(snapshot))
    return result


def validate_saved(saved: dict, report: dict, observation: dict | None) -> None:
    """Equality to fresh server records, not a caller's rehashed approval claim."""
    current = prepare(report, observation)
    if current["status"] != "PREPARATION_ONLY" or saved != current:
        raise PlanError("Handoff changed or expired; fresh Human input review required")
