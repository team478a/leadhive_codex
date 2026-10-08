"""Pure, synthetic-contract validation. No adapter execution or authorization."""

import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanError(ValueError):
    pass


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InputValue(FrozenContract):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(max_length=20000)


class PlanStep(FrozenContract):
    kind: Literal["confirm_local", "confirm_post", "submit"]
    url: str
    method: Literal["NONE", "POST"]


class ExecutionPlan(FrozenContract):
    """A proposed plan, never a Human proof or permission to send."""

    contract_version: Literal[1] = 1
    adapter_id: Literal["fixture_cf7", "fixture_js_confirmation"]
    adapter_version: Literal["1"]
    project_id: UUID
    company_id: UUID
    form_id: str = Field(min_length=1, max_length=200)
    form_url: str
    field_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    route_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_version: int = Field(ge=1)
    sender: tuple[InputValue, ...]
    subject: str = Field(max_length=2000)
    body: str = Field(min_length=1, max_length=20000)
    field_values: tuple[InputValue, ...]
    steps: tuple[PlanStep, ...]

    @model_validator(mode="after")
    def validate_contract(self):
        # This first stage accepts anonymous fixtures only. DNS safety and runtime
        # network enforcement are deliberately not implied by this lexical check.
        allowed = {
            "https://fixture.example/contact",
            "https://fixture.example/confirm",
            "https://fixture.example/submit",
        }
        if self.form_url != "https://fixture.example/contact":
            raise ValueError("Only the anonymous fixture origin is supported")
        for step in self.steps:
            if step.url not in allowed or urlsplit(step.url).netloc != "fixture.example":
                raise ValueError("Unknown fixture destination")
        for values in (self.sender, self.field_values):
            names = [item.name for item in values]
            if not names or len(names) != len(set(names)):
                raise ValueError("Empty or duplicate input names")
        submit = PlanStep(kind="submit", url="https://fixture.example/submit", method="POST")
        local = PlanStep(kind="confirm_local", url=self.form_url, method="NONE")
        confirmation = PlanStep(
            kind="confirm_post", url="https://fixture.example/confirm", method="POST"
        )
        accepted = (
            ((submit,),)
            if self.adapter_id == "fixture_cf7"
            else ((local, submit), (confirmation, submit))
        )
        if self.steps not in accepted:
            raise ValueError("Unknown or repeated execution steps")
        return self


def plan_hash(plan: ExecutionPlan) -> str:
    # model_copy/model_construct can bypass Pydantic validation. Do not hash a
    # malformed contract into something that looks like an accepted snapshot.
    plan = ExecutionPlan.model_validate(plan.model_dump(mode="python"))
    data = plan.model_dump(mode="json")
    # Dictionary ordering is irrelevant; field values and step ordering are not.
    for key in ("sender", "field_values"):
        data[key] = sorted(data[key], key=lambda item: item["name"])
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_plan(
    snapshot: ExecutionPlan, current: ExecutionPlan, *, expected_hash: str, expected_version: int
) -> None:
    """Compare proposed data only; callers still need actual Human authorization."""
    if type(expected_version) is not int or expected_version < 1:
        raise PlanError("Invalid expected version")
    if snapshot.payload_version != expected_version or current.payload_version != expected_version:
        raise PlanError("Payload version changed; prepare again")
    if plan_hash(snapshot) != expected_hash:
        raise PlanError("Snapshot integrity mismatch")
    if plan_hash(current) != expected_hash:
        raise PlanError("Execution plan changed; prepare again")


class FixtureResult(FrozenContract):
    form_id: str
    attempt_id: UUID
    stage: Literal["confirmation", "final"]
    status: str


def classify_fixture_result(
    evidence: FixtureResult, *, form_id: str, attempt_id: UUID
) -> Literal["SUBMITTED", "UNKNOWN"]:
    """Synthetic evidence only, not a classifier for real CF7 wire responses.

    A validation error after interaction cannot prove non-acceptance. Retain
    UNKNOWN for every response except the exact synthetic acceptance contract.
    """
    if (
        evidence.form_id == form_id
        and evidence.attempt_id == attempt_id
        and evidence.stage == "final"
        and evidence.status == "fixture_accepted"
    ):
        return "SUBMITTED"
    return "UNKNOWN"
