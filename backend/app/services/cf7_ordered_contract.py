"""DOM-ordered inert mixed-fixture proposal. No dispatch or authorization."""

import hashlib
import json
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.cf7_candidate_contract import digest
from app.services.cf7_mixed_contract import MixedCandidate
from app.services.form_execution_plan import FrozenContract, PlanError


class PartRef(FrozenContract):
    kind: Literal["BASE_HIDDEN", "BASE_FIELD", "CHECKBOX", "RADIO", "EXTRA_HIDDEN"]
    name: str = Field(min_length=1, max_length=200)
    option_id: str = Field(default="", max_length=64)


def key(ref: PartRef) -> tuple[str, str, str]:
    return ref.kind, ref.name, ref.option_id


def values(plan: MixedCandidate) -> dict[tuple[str, str, str], str]:
    base = plan.groups.base
    result = {("BASE_HIDDEN", v.name, ""): v.value for v in base.hidden}
    result.update({("BASE_FIELD", v.name, ""): v.value for v in base.field_values})
    for group in plan.groups.groups:
        result.update(
            {
                ("CHECKBOX", group.name, o.option_id): o.value
                for o, c in zip(group.options, group.choices, strict=True)
                if c.checked
            }
        )
    result.update(
        {
            ("RADIO", plan.radio.group.name, o.option_id): o.value
            for o, c in zip(plan.radio.group.options, plan.radio.group.choices, strict=True)
            if c.checked
        }
    )
    result[("EXTRA_HIDDEN", plan.hidden.extra.name, "")] = plan.hidden.extra.value
    return result


class OrderedCandidate(FrozenContract):
    contract_version: Literal["cf7-dom-ordered-lab-v1"] = "cf7-dom-ordered-lab-v1"
    canonicalization_version: Literal["cf7-dom-order-json-v1"] = "cf7-dom-order-json-v1"
    source_kind: Literal["CONTROLLED_FIXTURE"]
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    execution_allowed: Literal[False] = False
    eligible_for_approval: Literal[False] = False
    mixed: MixedCandidate
    order: tuple[PartRef, ...] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def complete_order(self) -> "OrderedCandidate":
        refs = [key(ref) for ref in self.order]
        if len(refs) != len(set(refs)) or set(refs) != set(values(self.mixed)):
            raise ValueError("Order must contain every successful control exactly once")
        return self


def canonical(candidate: OrderedCandidate) -> dict[str, Any]:
    return OrderedCandidate.model_validate(candidate.model_dump(mode="python")).model_dump(
        mode="json"
    )


def wire(candidate: OrderedCandidate) -> tuple[str, bytes]:
    data = canonical(candidate)
    plan = OrderedCandidate.model_validate_json(json.dumps(data))
    boundary = "----LeadHiveCF7Ordered" + digest(data)[:32]
    lookup = values(plan.mixed)
    chunks = []
    for ref in plan.order:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,197}(?:\[\])?", ref.name):
            raise PlanError("Unsafe multipart name")
        value = re.sub(r"\r\n|\r|\n", "\r\n", lookup[key(ref)])
        if boundary in value:
            raise PlanError("Multipart boundary collision")
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{ref.name}"'
                f"\r\n\r\n{value}\r\n"
            ).encode()
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    body = b"".join(chunks)
    if len(body) > 65536:
        raise PlanError("Multipart too large")
    return "multipart/form-data; boundary=" + boundary, body


def snapshot(candidate: OrderedCandidate) -> dict[str, Any]:
    data = canonical(candidate)
    kind, body = wire(candidate)
    return {
        "contract": data,
        "contract_hash": digest(data),
        "content_type": kind,
        "wire_sha256": hashlib.sha256(body).hexdigest(),
        "wire_size": len(body),
    }


def validate_snapshot(
    saved: dict,
    current: OrderedCandidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    plan = OrderedCandidate.model_validate_json(json.dumps(saved.get("contract")))
    base = plan.mixed.groups.base
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
        raise PlanError("Ordered proposal changed; new preparation required")
