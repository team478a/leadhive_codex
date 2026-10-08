"""One allowlisted non-secret hidden field, managed fixture only."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import model_validator

from app.services.cf7_candidate_contract import CF7Candidate, digest
from app.services.cf7_candidate_contract import wire as base_wire
from app.services.cf7_inert_multipart import append_parts
from app.services.form_execution_plan import FrozenContract, PlanError


class ExtraHidden(FrozenContract):
    name: Literal["leadhive_lab_context"]
    value: Literal["fixture-business-context"]
    purpose: Literal["FIXED_LAB_ROUTING_CONTEXT"]


class ExtraHiddenCandidate(FrozenContract):
    contract_version: Literal["cf7-extra-hidden-lab-v1"] = "cf7-extra-hidden-lab-v1"
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    source_kind: Literal["CONTROLLED_FIXTURE"]
    canonicalization_version: Literal["cf7-extra-hidden-json-v1"] = "cf7-extra-hidden-json-v1"
    wire_order: Literal["base-then-extra-hidden-v1"] = "base-then-extra-hidden-v1"
    execution_allowed: Literal[False] = False
    eligible_for_approval: Literal[False] = False
    base: CF7Candidate
    extra: ExtraHidden

    @model_validator(mode="after")
    def binding(self) -> "ExtraHiddenCandidate":
        if (
            self.base.form_url != "https://managed.example/contact/"
            or self.base.rest_root != "https://managed.example/wp-json/"
        ):
            raise ValueError("Only the named managed fixture is supported")
        names = {v.name for v in self.base.hidden} | {v.name for v in self.base.controls}
        if self.extra.name in names or self.extra.name + "[]" in names:
            raise ValueError("Extra hidden conflicts with another control")
        if (
            sum(len(v.value.encode()) for v in (*self.base.hidden, *self.base.field_values))
            + len(self.extra.value.encode())
            > 40000
        ):
            raise ValueError("Combined payload too large")
        return self


def canonical(candidate: ExtraHiddenCandidate) -> dict[str, Any]:
    return ExtraHiddenCandidate.model_validate(candidate.model_dump(mode="python")).model_dump(
        mode="json"
    )


def wire(candidate: ExtraHiddenCandidate) -> tuple[str, bytes]:
    data = canonical(candidate)
    plan = ExtraHiddenCandidate.model_validate_json(json.dumps(data))
    return append_parts(
        *base_wire(plan.base),
        [(plan.extra.name, plan.extra.value)],
        "----LeadHiveCF7Hidden" + digest(data)[:32],
    )


def snapshot(candidate: ExtraHiddenCandidate) -> dict[str, Any]:
    data = canonical(candidate)
    content_type, body = wire(candidate)
    return {
        "contract": data,
        "contract_hash": digest(data),
        "content_type": content_type,
        "wire_sha256": hashlib.sha256(body).hexdigest(),
        "wire_size": len(body),
    }


def validate_snapshot(
    saved: dict,
    current: ExtraHiddenCandidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    parsed = ExtraHiddenCandidate.model_validate_json(json.dumps(saved.get("contract")))
    if (
        type(expected_version) is not int
        or expected_version < 1
        or saved != snapshot(parsed)
        or digest(saved) != expected_hash
        or snapshot(current) != saved
        or parsed.base.payload_version != expected_version
        or (
            parsed.base.project_id,
            parsed.base.company_id,
            parsed.base.source_draft_id,
            parsed.base.form_profile_id,
        )
        != (project_id, company_id, source_draft_id, form_profile_id)
    ):
        raise PlanError("Hidden proposal changed; new preparation required")
