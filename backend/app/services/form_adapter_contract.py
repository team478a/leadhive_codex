"""Connection contract only. No network, approval API, registry executor or dispatch."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field, TypeAdapter, model_validator

from app.services.form_execution_plan import FrozenContract, InputValue, PlanError, PlanStep

CONTACT = "https://fixture.example/contact"
SUBMIT = "https://fixture.example/submit"


class ExecutableFormPlan(FrozenContract):
    # This separate contract does not widen the non-executable ExecutionPlan v1.
    contract_version: Literal[1] = 1
    canonicalization_version: Literal["adapter-json-v1"] = "adapter-json-v1"
    environment: Literal["CONTROLLED_LAB"]
    adapter_id: Literal["controlled_lab_single_post"]
    adapter_version: Literal["1"]
    project_id: UUID
    company_id: UUID
    source_draft_id: UUID
    form_profile_id: UUID
    form_id: str = Field(min_length=1, max_length=200)
    channel: Literal["form"] = "form"
    delivery_method: Literal["form_adapter"] = "form_adapter"
    form_url: Literal["https://fixture.example/contact"]
    field_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    route_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_version: int = Field(ge=1)
    sender: tuple[InputValue, ...] = Field(min_length=4, max_length=4)
    subject: str = Field(max_length=1000)
    body: str = Field(min_length=1, max_length=20000)
    field_values: tuple[InputValue, ...] = Field(min_length=1, max_length=100)
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def finite_registry(self):
        if self.steps != (PlanStep(kind="submit", url=SUBMIT, method="POST"),):
            raise ValueError("Only the controlled single POST contract is registered")
        for values in (self.sender, self.field_values):
            names = [v.name for v in values]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate input names")
        if {v.name for v in self.sender} != {"name", "email", "company", "phone"}:
            raise ValueError("Complete sender snapshot required")
        sender = {v.name: v.value for v in self.sender}
        if not sender["name"].strip():
            raise ValueError("Sender name required")
        if str(TypeAdapter(EmailStr).validate_python(sender["email"])) != sender["email"]:
            raise ValueError("Sender email must already be canonical")
        if sum(len(v.name) + len(v.value) for v in self.field_values) > 40000:
            raise ValueError("Fields too large")
        return self


def canonical_plan(plan: ExecutableFormPlan) -> dict:
    # Revalidation prevents model_copy/model_construct from legitimizing bad input.
    plan = ExecutableFormPlan.model_validate(plan.model_dump(mode="python"))
    data = plan.model_dump(mode="json")
    for key in ("sender", "field_values"):
        data[key] = sorted(data[key], key=lambda item: item["name"])
    return data


def digest(data: dict) -> str:
    encoded = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def adapter_plan_hash(plan: ExecutableFormPlan) -> str:
    return digest(canonical_plan(plan))


def adapter_snapshot(plan: ExecutableFormPlan) -> dict:
    """Prepare immutable data, never authorize execution or persist an approval."""
    data = canonical_plan(plan)
    return {
        "project_id": data["project_id"],
        "company_id": data["company_id"],
        "source_draft_id": data["source_draft_id"],
        "channel": "form",
        "delivery_method": "form_adapter",
        "form_url": data["form_url"],
        "form_action_url": data["steps"][0]["url"],
        "subject": data["subject"],
        "body": data["body"],
        "sender": {v["name"]: v["value"] for v in data["sender"]},
        "field_values": {v["name"]: v["value"] for v in data["field_values"]},
        "payload_version": data["payload_version"],
        "canonicalization_version": "json-v1",
        "attachment_metadata": [],
        "adapter_plan": data,
        "adapter_plan_hash": digest(data),
    }


def validate_adapter_snapshot(
    snapshot: dict,
    current: ExecutableFormPlan,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
) -> None:
    if type(expected_version) is not int or expected_version < 1:
        raise PlanError("Invalid expected version")
    parsed = ExecutableFormPlan.model_validate_json(json.dumps(snapshot.get("adapter_plan")))
    if (
        parsed.project_id != project_id
        or parsed.company_id != company_id
        or parsed.source_draft_id != source_draft_id
        or parsed.payload_version != expected_version
        or snapshot != adapter_snapshot(parsed)
        or digest(snapshot) != expected_hash
        or canonical_plan(current) != canonical_plan(parsed)
    ):
        raise PlanError("Adapter snapshot binding changed; prepare and approve again")
