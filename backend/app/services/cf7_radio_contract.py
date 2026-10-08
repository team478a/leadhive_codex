"""Inert, fixed managed-fixture radio contract. No runtime adapter registration."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.cf7_candidate_contract import CF7Candidate, digest
from app.services.cf7_candidate_contract import wire as base_wire
from app.services.cf7_checkbox_group_contract import CheckboxGroup
from app.services.cf7_inert_multipart import append_parts
from app.services.form_execution_plan import FrozenContract, PlanError


class RadioGroup(CheckboxGroup):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,97}$")
    required: Literal[True] = True
    min_selected: Literal[1] = 1
    max_selected: Literal[1] = 1

    @model_validator(mode="after")
    def initial_state(self) -> "RadioGroup":
        if sum(option.initially_checked for option in self.options) > 1:
            raise ValueError("Ambiguous initial radio state")
        return self


class RadioCandidate(FrozenContract):
    contract_version: Literal["cf7-radio-lab-v1"] = "cf7-radio-lab-v1"
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    source_kind: Literal["CONTROLLED_FIXTURE"]
    canonicalization_version: Literal["cf7-radio-json-v1"] = "cf7-radio-json-v1"
    wire_order: Literal["base-then-radio-v1"] = "base-then-radio-v1"
    execution_allowed: Literal[False] = False
    eligible_for_approval: Literal[False] = False
    base: CF7Candidate
    group: RadioGroup

    @model_validator(mode="after")
    def binding(self) -> "RadioCandidate":
        if (
            self.base.form_url != "https://managed.example/contact/"
            or self.base.rest_root != "https://managed.example/wp-json/"
        ):
            raise ValueError("Only the named managed fixture is supported")
        names = {item.name for item in self.base.controls} | {
            item.name for item in self.base.hidden
        }
        if self.group.name in names or self.group.name + "[]" in names:
            raise ValueError("Radio name collides with scalar or hidden")
        size = sum(len(v.value.encode()) for v in (*self.base.hidden, *self.base.field_values))
        size += sum(
            len(o.value.encode())
            for o, c in zip(self.group.options, self.group.choices, strict=True)
            if c.checked
        )
        if size > 40000:
            raise ValueError("Combined payload too large")
        return self


def canonical(candidate: RadioCandidate) -> dict[str, Any]:
    return RadioCandidate.model_validate(candidate.model_dump(mode="python")).model_dump(
        mode="json"
    )


def wire(candidate: RadioCandidate) -> tuple[str, bytes]:
    data = canonical(candidate)
    plan = RadioCandidate.model_validate_json(json.dumps(data))
    option = next(
        o for o, c in zip(plan.group.options, plan.group.choices, strict=True) if c.checked
    )
    return append_parts(
        *base_wire(plan.base),
        [(plan.group.name, option.value)],
        "----LeadHiveCF7Radio" + digest(data)[:32],
    )


def snapshot(candidate: RadioCandidate) -> dict[str, Any]:
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
    current: RadioCandidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    parsed = RadioCandidate.model_validate_json(json.dumps(saved.get("contract")))
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
        raise PlanError("Radio proposal changed; new preparation required")
