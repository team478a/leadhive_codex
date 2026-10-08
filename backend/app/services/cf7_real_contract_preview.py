"""Bounded real-site evidence binding. No wire encoder, HTTP, approval or dispatch."""

import json
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, model_validator

from app.services.cf7_candidate_contract import digest, origin


class EvidenceControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,99}$")
    kind: Literal["text", "email", "tel", "textarea", "checkbox"]
    required: bool
    checkbox_value: str = Field(pattern=r"^[A-Za-z0-9_-]{0,200}$")
    maxlength: int | None = Field(default=None, ge=0, le=20000)

    @model_validator(mode="after")
    def option(self):
        if bool(self.checkbox_value) != (self.kind == "checkbox"):
            raise ValueError("Explicit checkbox value only")
        return self


class RealContractEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    definition_version: Literal["real-cf7-static-evidence-v1", "real-cf7-static-evidence-v2"]
    source_kind: Literal["REAL_SITE_STATIC_HTML"]
    form_url: str = Field(max_length=2000)
    plugin_version: Literal["6.1.4", "6.2"]
    rest_root: str = Field(max_length=2000)
    endpoint: str = Field(max_length=2200)
    hidden: dict[str, str]
    controls: list[EvidenceControl] = Field(min_length=1, max_length=50)
    dom_order: list[str] = Field(min_length=7, max_length=56)
    execution_allowed: Literal[False]
    eligible_for_approval: Literal[False]

    @model_validator(mode="after")
    def binding(self):
        site = origin(self.form_url)
        if self.rest_root != site + "/wp-json/":
            raise ValueError("Exact same-origin static REST root required")
        h = self.hidden
        if set(h) != {
            "_wpcf7",
            "_wpcf7_version",
            "_wpcf7_locale",
            "_wpcf7_unit_tag",
            "_wpcf7_container_post",
            "_wpcf7_posted_data_hash",
        }:
            raise ValueError("Only known metadata may be retained")
        if not re.fullmatch(r"[1-9][0-9]{0,9}", h["_wpcf7"]) or int(h["_wpcf7"]) > 2147483647:
            raise ValueError("Invalid form identity")
        if h["_wpcf7_version"] != self.plugin_version or h["_wpcf7_posted_data_hash"]:
            raise ValueError("Version or submission state mismatch")
        if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", h["_wpcf7_locale"]):
            raise ValueError("Invalid locale")
        container = h["_wpcf7_container_post"]
        if not re.fullmatch(r"0|[1-9][0-9]{0,9}", container):
            raise ValueError("Invalid container")
        prefix = "wpcf7-f" + h["_wpcf7"] + ("-p" + container if container != "0" else "")
        if not re.fullmatch(re.escape(prefix) + r"-o[1-9][0-9]{0,9}", h["_wpcf7_unit_tag"]):
            raise ValueError("Invalid unit identity")
        route = "contact-form-7/v1/contact-forms/" + h["_wpcf7"] + "/feedback"
        if self.endpoint != self.rest_root + route:
            raise ValueError("Invalid feedback route")
        names = [c.name for c in self.controls]
        if len(names) != len(set(names)) or set(names) & set(h):
            raise ValueError("Ambiguous controls")
        if len(self.dom_order) != len(set(self.dom_order)) or set(self.dom_order) != set(
            names
        ) | set(h):
            raise ValueError("Incomplete DOM order")
        return self


def preview(report: dict, observation: dict | None) -> dict:
    """Rebuilt server input report + saved observation only. Never accept client snapshots."""
    reasons = []
    observation = observation or {}
    snapshot = report["snapshot"]
    if (
        report["snapshot_hash"] != digest(snapshot)
        or snapshot.get("definition_version") != "saved-form-input-review-v2"
    ):
        reasons.append("INPUT_SNAPSHOT_CHANGED")
    if not report["can_record"] or report["review_status"] != "RECORDED":
        reasons.append("INPUT_CONFIRMATION_REQUIRED")
    if not report.get("reviewed_by") or not report.get("reviewed_at"):
        reasons.append("INPUT_CONFIRMATION_REQUIRED")
    expiries = []
    for expiry in (report.get("review_expires_at"), observation.get("expires_at")):
        try:
            value = datetime.fromisoformat(str(expiry))
            if value.tzinfo is None or value <= datetime.now(timezone.utc):
                reasons.append("CONFIRMATION_EXPIRED")
            else:
                expiries.append(value)
        except ValueError:
            reasons.append("CONFIRMATION_EXPIRED")
    if (
        observation.get("freshness") != "CURRENT"
        or observation.get("structure_status") != "SAME_STRUCTURE"
    ):
        reasons.append("OBSERVATION_UNVERIFIED")
    if snapshot["observation_hash"] != digest(json.loads(json.dumps(observation, default=str))):
        reasons.append("OBSERVATION_CHANGED")
    contract = None
    try:
        evidence = RealContractEvidence.model_validate(
            (observation.get("cf7_static") or {}).get("contract_evidence")
        ).model_dump()
        if (
            evidence["form_url"] != snapshot["form_url"]
            or evidence["plugin_version"] != snapshot["plugin_version"]
        ):
            raise ValueError("Target/version mismatch")
        rows = snapshot["rows"]
        by_name = {r["name"]: r for r in rows}
        controls = evidence["controls"]
        if len(by_name) != len(rows) or set(by_name) != {c["name"] for c in controls}:
            raise ValueError("Input set mismatch")
        parts = []
        for name in evidence["dom_order"]:
            if name in evidence["hidden"]:
                parts.append({"name": name, "value": evidence["hidden"][name], "kind": "metadata"})
                continue
            row = by_name[name]
            control = next(c for c in controls if c["name"] == name)
            values = row["values"]
            if (
                row["field_type"] != control["kind"]
                or row["required"] != control["required"]
                or len(values) > 1
            ):
                raise ValueError("Requiredness/value mismatch")
            if control["required"] and (not values or not values[0].strip()):
                raise ValueError("Missing required input")
            input_value = values[0] if values else ""
            if control["kind"] in {"text", "email", "tel"} and re.search(r"[\r\n]", input_value):
                raise ValueError("Single-line browser sanitization would change input")
            normalized = re.sub(r"\r\n|\r", "\n", input_value)
            if (
                control["maxlength"] is not None
                and len(normalized.encode("utf-16-le")) // 2 > control["maxlength"]
            ):
                raise ValueError("Browser UTF-16 maxlength exceeded")
            if control["kind"] == "checkbox":
                if row["state"] != "HUMAN_SELECTION_RECORDED" or values not in (
                    [],
                    [control["checkbox_value"]],
                ):
                    raise ValueError("Explicit selection mismatch")
                if not values:
                    continue  # Browser omits an unchecked checkbox.
            elif row["state"] not in {
                "SENDER_VALUE_PROPOSED",
                "UNAPPROVED_DRAFT_VALUE",
                "OPTIONAL_LEAVE_BLANK",
            }:
                raise ValueError("Unconfirmed input state")
            if control["kind"] == "email" and values and values[0]:
                TypeAdapter(EmailStr).validate_python(values[0])
            parts.append(
                {"name": name, "value": values[0] if values else "", "kind": control["kind"]}
            )
        contract = {
            "definition_version": "real-cf7-contract-preview-v1",
            "source_kind": "REAL_SITE_STATIC_HTML",
            "contract_family": "cf7-" + evidence["plugin_version"],
            "plugin_version_evidence": "HTML_MARKER_ONLY",
            "input_snapshot_hash": report["snapshot_hash"],
            "source_hash": snapshot["source_hash"],
            "project_id": snapshot["project_id"],
            "company_id": snapshot["company_id"],
            "profile_id": snapshot["profile_id"],
            "draft_id": snapshot["draft_id"],
            "draft_hash": snapshot["draft_hash"],
            "profile_fingerprint": snapshot["profile_fingerprint"],
            "evidence_hash": digest(evidence),
            "form_url": evidence["form_url"],
            "endpoint": evidence["endpoint"],
            "parts": parts,
            "reviewed_by": report.get("reviewed_by"),
            "expires_at": min(expiries).isoformat() if len(expiries) == 2 else None,
            "execution_allowed": False,
            "eligible_for_approval": False,
        }
    except (ValueError, TypeError, KeyError):
        reasons.append("CONTRACT_EVIDENCE_UNVERIFIED")
    if reasons:
        contract = None
    return {
        "status": "PREVIEW_ONLY" if contract else "HOLD",
        "reasons": list(dict.fromkeys(reasons)),
        "contract": contract,
        "contract_hash": digest(contract) if contract else None,
        "execution_allowed": False,
        "eligible_for_approval": False,
        "live_fetch_performed": False,
    }
