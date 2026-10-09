"""CF7 6.1.6 pinned managed-fixture contract. No HTTP, DB or authorization."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.cf7_candidate_contract import CF7ValidatedFields, digest
from app.services.cf7_extra_hidden_contract import ExtraHidden
from app.services.cf7_ordered_contract import PartRef, key, render_ordered
from app.services.form_execution_plan import FrozenContract, PlanError


class CF7616Fields(CF7ValidatedFields):
    contract_version: Literal["cf7-616-fields-v1"] = "cf7-616-fields-v1"
    canonicalization_version: Literal["cf7-616-fields-json-v1"] = "cf7-616-fields-json-v1"
    plugin_version: Literal["6.1.6"] = "6.1.6"
    source_commit: Literal["3decbc4d7a230d8331e77243a6747b5ec6807d78"] = (
        "3decbc4d7a230d8331e77243a6747b5ec6807d78"
    )


class CF7616Candidate(FrozenContract):
    contract_version: Literal["cf7-616-ordered-lab-v1"] = "cf7-616-ordered-lab-v1"
    canonicalization_version: Literal["cf7-616-ordered-json-v1"] = "cf7-616-ordered-json-v1"
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    source_kind: Literal["CONTROLLED_FIXTURE"]
    execution_allowed: Literal[False] = False
    eligible_for_approval: Literal[False] = False
    base: CF7616Fields
    extra: ExtraHidden | None = None
    order: tuple[PartRef, ...] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def binding(self) -> "CF7616Candidate":
        if (
            self.base.form_url != "https://managed.example/contact/"
            or self.base.rest_root != "https://managed.example/wp-json/"
        ):
            raise ValueError("Named managed fixture only")
        names = {v.name for v in self.base.hidden} | {v.name for v in self.base.controls}
        if self.extra and self.extra.name in names:
            raise ValueError("Extra hidden conflicts with another control")
        lookup = values(self)
        refs = [key(ref) for ref in self.order]
        if len(set(refs)) != len(refs) or set(refs) != set(lookup):
            raise ValueError("Every successful control required exactly once")
        if sum(len(value.encode("utf-8")) for value in lookup.values()) > 40000:
            raise ValueError("Combined payload too large")
        return self


def values(plan: CF7616Candidate) -> dict[tuple[str, str, str], str]:
    result = {("BASE_HIDDEN", v.name, ""): v.value for v in plan.base.hidden}
    result.update({("BASE_FIELD", v.name, ""): v.value for v in plan.base.field_values})
    if plan.extra:
        result[("EXTRA_HIDDEN", plan.extra.name, "")] = plan.extra.value
    return result


def canonical(plan: CF7616Candidate) -> dict[str, Any]:
    # Revalidate even model_construct/model_copy inputs at the public boundary.
    return CF7616Candidate.model_validate(plan.model_dump(mode="python")).model_dump(mode="json")


def wire(plan: CF7616Candidate) -> tuple[str, bytes]:
    data = canonical(plan)
    validated = CF7616Candidate.model_validate_json(json.dumps(data))
    return render_ordered(data, validated.order, values(validated))


def snapshot(plan: CF7616Candidate) -> dict[str, Any]:
    data = canonical(plan)
    content_type, body = wire(plan)
    return {
        "contract": data,
        "contract_hash": digest(data),
        "content_type": content_type,
        "wire_sha256": hashlib.sha256(body).hexdigest(),
        "wire_size": len(body),
    }


def validate_snapshot(
    saved: dict[str, Any],
    current: CF7616Candidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    plan = CF7616Candidate.model_validate_json(json.dumps(saved.get("contract")))
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
        raise PlanError("6.1.6 proposal changed; new preparation required")
