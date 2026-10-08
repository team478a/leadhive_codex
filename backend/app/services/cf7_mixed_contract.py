"""Combined controlled-fixture proposal; no execution or authorization."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import model_validator

from app.services.cf7_candidate_contract import digest
from app.services.cf7_checkbox_group_contract import GroupCandidate
from app.services.cf7_checkbox_group_contract import wire as group_wire
from app.services.cf7_extra_hidden_contract import ExtraHiddenCandidate
from app.services.cf7_inert_multipart import append_parts
from app.services.cf7_radio_contract import RadioCandidate
from app.services.form_execution_plan import FrozenContract, PlanError


class MixedCandidate(FrozenContract):
    contract_version: Literal["cf7-mixed-lab-v1"] = "cf7-mixed-lab-v1"
    canonicalization_version: Literal["cf7-mixed-json-v1"] = "cf7-mixed-json-v1"
    source_kind: Literal["CONTROLLED_FIXTURE"]
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    wire_order: Literal["base-groups-radio-hidden-v1"] = "base-groups-radio-hidden-v1"
    execution_allowed: Literal[False] = False
    eligible_for_approval: Literal[False] = False
    groups: GroupCandidate
    radio: RadioCandidate
    hidden: ExtraHiddenCandidate

    @model_validator(mode="after")
    def binding(self) -> "MixedCandidate":
        if self.groups.base != self.radio.base or self.groups.base != self.hidden.base:
            raise ValueError("All components require identical base and scope")
        names = [g.name.removesuffix("[]") for g in self.groups.groups]
        names += [self.radio.group.name, self.hidden.extra.name]
        if len(names) != len(set(names)):
            raise ValueError("Mixed field name collision")
        values = [v.value for v in (*self.groups.base.hidden, *self.groups.base.field_values)]
        for group in (*self.groups.groups, self.radio.group):
            values += [
                o.value for o, c in zip(group.options, group.choices, strict=True) if c.checked
            ]
        values.append(self.hidden.extra.value)
        if sum(len(v.encode()) for v in values) > 40000:
            raise ValueError("Combined mixed payload too large")
        return self


def canonical(candidate: MixedCandidate) -> dict[str, Any]:
    return MixedCandidate.model_validate(candidate.model_dump(mode="python")).model_dump(
        mode="json"
    )


def wire(candidate: MixedCandidate) -> tuple[str, bytes]:
    data = canonical(candidate)
    plan = MixedCandidate.model_validate_json(json.dumps(data))
    option = next(
        o
        for o, c in zip(plan.radio.group.options, plan.radio.group.choices, strict=True)
        if c.checked
    )
    return append_parts(
        *group_wire(plan.groups),
        [(plan.radio.group.name, option.value), (plan.hidden.extra.name, plan.hidden.extra.value)],
        "----LeadHiveCF7Mixed" + digest(data)[:32],
    )


def snapshot(candidate: MixedCandidate) -> dict[str, Any]:
    data = canonical(candidate)
    kind, body = wire(candidate)
    return dict(
        contract=data,
        contract_hash=digest(data),
        content_type=kind,
        wire_sha256=hashlib.sha256(body).hexdigest(),
        wire_size=len(body),
    )


def validate_snapshot(
    saved: dict,
    current: MixedCandidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    plan = MixedCandidate.model_validate_json(json.dumps(saved.get("contract")))
    base = plan.groups.base
    if (
        type(expected_version) is not int
        or expected_version < 1
        or saved != snapshot(plan)
        or digest(saved) != expected_hash
        or snapshot(current) != saved
        or base.payload_version != expected_version
        or (base.project_id, base.company_id, base.source_draft_id, base.form_profile_id)
        != (project_id, company_id, source_draft_id, form_profile_id)
    ):
        raise PlanError("Mixed proposal changed; new preparation required")
