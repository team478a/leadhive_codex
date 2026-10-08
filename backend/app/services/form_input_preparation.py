"""Saved input review snapshot. Never a CF7 wire contract or send approval."""

import json
from collections import Counter
from datetime import datetime, timezone

from app.services.cf7_candidate_contract import digest


def prepare(
    material: dict, fields: list[dict], observation: dict | None, *, source_hash: str
) -> dict:
    observation = observation or {}
    static = observation.get("cf7_static") or {}
    shape = static.get("contract_shape") or {}
    reasons = []
    try:
        expiry = datetime.fromisoformat(str(observation.get("expires_at")))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            reasons.append("OBSERVATION_UNVERIFIED")
    except ValueError:
        reasons.append("OBSERVATION_UNVERIFIED")
    boundary = material["technical_diagnostic"]["boundary"]
    if boundary == "BLOCKED" or observation.get("sales_prohibition_detected") is True:
        reasons.append("CONTACT_BLOCKED")
    if boundary == "HUMAN_REQUIRED" or observation.get("captcha_state") == "DETECTED":
        reasons.append("CAPTCHA")
    if material["technical_diagnostic"]["route"] != "CF7_CANDIDATE":
        reasons.append("CF7_UNVERIFIED")
    if (
        observation.get("freshness") != "CURRENT"
        or observation.get("structure_status") != "SAME_STRUCTURE"
        or observation.get("method_is_post") is not True
    ):
        reasons.append("OBSERVATION_UNVERIFIED")
    if static.get("status") != "CF7_CANDIDATE" or static.get("version") not in ("6.1.4", "6.2"):
        reasons.append("VERSION_UNVERIFIED")
    if shape.get("review_hidden_shape_valid") is not True:
        reasons.append("HIDDEN_UNVERIFIED")
    if static.get("rest_link_same_origin") is not True or static.get("base_override") is not False:
        reasons.append("REST_ROOT_UNVERIFIED")
    if any(
        type(static.get(k)) is not int or static[k] != 0
        for k in ("file_inputs", "missing_names", "unsupported_controls")
    ):
        reasons.append("UNSUPPORTED_STRUCTURE")
    for key in (
        "extra_hidden",
        "invalid_names",
        "repeated_names",
        "radio_controls",
        "select_controls",
        "disabled_controls",
    ):
        if type(shape.get(key)) is not int or shape[key] != 0:
            reasons.append("UNSUPPORTED_STRUCTURE")
    if not material.get("draft_id"):
        reasons.append("DRAFT_MISSING")
    names = Counter(f.get("name") for f in fields if f.get("field_type") != "hidden")
    rows = []
    for item in material["items"]:
        field = next(
            (f for f in fields if f["position"] == item["position"] and f["name"] == item["name"]),
            None,
        )
        if item["review_state"] == "DO_NOT_FILL":
            if field and field["field_type"] == "file":
                reasons.append("UNSUPPORTED_STRUCTURE")
            continue
        state = item["review_state"]
        values = [item["proposed_value"]] if item["proposed_value"] is not None else []
        resolved = state in {
            "SENDER_VALUE_PROPOSED",
            "UNAPPROVED_DRAFT_VALUE",
            "OPTIONAL_LEAVE_BLANK",
        }
        if (
            field
            and field["field_type"] == "checkbox"
            and names[item["name"]] == 1
            and len(field.get("options") or []) == 1
        ):
            option = field["options"][0].get("value")
            value = field.get("recommended_value")
            if (
                field.get("decision_source") == "MANUAL"
                and isinstance(option, str)
                and option
                and (value == option or not field["required"] and value == "")
            ):
                values = [value] if value else []
                resolved = True
                state = "HUMAN_SELECTION_RECORDED"
        if not resolved or names[item["name"]] != 1 or not item["name"]:
            reasons.append("INPUT_REVIEW_REQUIRED")
        if item["required"] and not values:
            reasons.append("REQUIRED_VALUE_MISSING")
        rows.append(
            {
                "position": item["position"],
                "name": item["name"],
                "label": item["label"],
                "required": item["required"],
                "field_type": field["field_type"] if field else None,
                "values": values,
                "state": state,
            }
        )
    if not rows:
        reasons.append("INPUT_REVIEW_REQUIRED")
    if (
        len(rows) > 100
        or sum(len(value.encode()) for row in rows for value in row["values"]) > 40000
    ):
        reasons.append("UNSUPPORTED_STRUCTURE")
    snapshot = {
        "definition_version": "saved-form-input-review-v2",
        "profile_id": str(material["profile_id"]),
        "project_id": str(material["project_id"]),
        "company_id": str(material["company_id"]),
        "form_url": material["form_url"],
        "profile_fingerprint": material["profile_fingerprint"],
        "source_hash": source_hash,
        "draft_id": str(material["draft_id"]) if material.get("draft_id") else None,
        "draft_hash": material["draft_hash"],
        "plugin_version": static.get("version")
        if static.get("version") in ("6.1.4", "6.2")
        else None,
        "observation_hash": digest(json.loads(json.dumps(observation, default=str))),
        "observation_expires_at": str(observation.get("expires_at"))
        if observation.get("expires_at")
        else None,
        "rows": rows,
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
    reasons = list(dict.fromkeys(reasons))
    return {
        "snapshot": snapshot,
        "snapshot_hash": digest(snapshot),
        "can_record": not reasons,
        "reasons": reasons,
        "review_status": "NOT_RECORDED",
        "execution_allowed": False,
        "eligible_for_approval": False,
        "live_fetch_performed": False,
    }
