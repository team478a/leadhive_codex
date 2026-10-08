"""Pinned CF7 6.2 managed-fixture bytes only. No network, approval or dispatch."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.cf7_candidate_contract import CF7ValidatedFields, digest
from app.services.cf7_checkbox_group_contract import CheckboxGroup
from app.services.cf7_extra_hidden_contract import ExtraHidden
from app.services.cf7_ordered_contract import PartRef, key, render_ordered
from app.services.cf7_radio_contract import RadioGroup
from app.services.form_execution_plan import FrozenContract, PlanError


class CF762Fields(CF7ValidatedFields):
    contract_version: Literal["cf7-62-fields-v1"] = "cf7-62-fields-v1"
    canonicalization_version: Literal["cf7-62-fields-json-v1"] = "cf7-62-fields-json-v1"
    plugin_version: Literal["6.2"] = "6.2"
    source_commit: Literal["34acb3a6995b403274820c5ea42abd01b754c03b"] = (
        "34acb3a6995b403274820c5ea42abd01b754c03b"
    )


class CF762Candidate(FrozenContract):
    contract_version: Literal["cf7-62-ordered-lab-v1"] = "cf7-62-ordered-lab-v1"
    canonicalization_version: Literal["cf7-62-ordered-json-v1"] = "cf7-62-ordered-json-v1"
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    source_kind: Literal["CONTROLLED_FIXTURE"]
    execution_allowed: Literal[False] = False
    eligible_for_approval: Literal[False] = False
    base: CF762Fields
    groups: tuple[CheckboxGroup, ...] = Field(default=(), max_length=10)
    radio: RadioGroup | None = None
    extra: ExtraHidden | None = None
    order: tuple[PartRef, ...] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def binding(self) -> "CF762Candidate":
        if (
            self.base.form_url != "https://managed.example/contact/"
            or self.base.rest_root != "https://managed.example/wp-json/"
        ):
            raise ValueError("Named managed fixture only")
        names = [v.name for v in self.base.hidden] + [v.name for v in self.base.controls]
        names += [g.name.removesuffix("[]") for g in self.groups]
        names += [self.radio.name] if self.radio else []
        names += [self.extra.name] if self.extra else []
        ids = [g.group_id for g in self.groups]
        ids += [self.radio.group_id] if self.radio else []
        if len(set(names)) != len(names) or len(set(ids)) != len(ids):
            raise ValueError("Conflicting control identity")
        option_count = sum(len(g.options) for g in self.groups)
        option_count += len(self.radio.options) if self.radio else 0
        if option_count > 50:
            raise ValueError("Option budget exceeded")
        lookup = values(self)
        refs = [key(ref) for ref in self.order]
        if len(set(refs)) != len(refs) or set(refs) != set(lookup):
            raise ValueError("Every successful control required exactly once")
        if sum(len(v.encode()) for v in lookup.values()) > 40000:
            raise ValueError("Combined payload too large")
        return self


def values(plan: CF762Candidate) -> dict[tuple[str, str, str], str]:
    result = {("BASE_HIDDEN", v.name, ""): v.value for v in plan.base.hidden}
    result.update({("BASE_FIELD", v.name, ""): v.value for v in plan.base.field_values})
    for kind, groups in (
        ("CHECKBOX", plan.groups),
        ("RADIO", (plan.radio,) if plan.radio else ()),
    ):
        for group in groups:
            for option, choice in zip(group.options, group.choices, strict=True):
                if choice.checked:
                    result[(kind, group.name, option.option_id)] = option.value
    if plan.extra:
        result[("EXTRA_HIDDEN", plan.extra.name, "")] = plan.extra.value
    return result


def canonical(plan: CF762Candidate) -> dict[str, Any]:
    return CF762Candidate.model_validate(plan.model_dump(mode="python")).model_dump(mode="json")


def wire(plan: CF762Candidate) -> tuple[str, bytes]:
    data = canonical(plan)
    validated = CF762Candidate.model_validate_json(json.dumps(data))
    return render_ordered(data, validated.order, values(validated))


def snapshot(plan: CF762Candidate) -> dict[str, Any]:
    data = canonical(plan)
    kind, body = wire(plan)
    return {
        "contract": data,
        "contract_hash": digest(data),
        "content_type": kind,
        "wire_sha256": hashlib.sha256(body).hexdigest(),
        "wire_size": len(body),
    }


def validate_snapshot(
    saved: dict,
    current: CF762Candidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    plan = CF762Candidate.model_validate_json(json.dumps(saved.get("contract")))
    base = plan.base
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
        raise PlanError("6.2 proposal changed; new preparation required")
