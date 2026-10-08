"""Managed-fixture proposal only. No DB, HTTP, approval or adapter registration.

The existing CF7 v1 contract remains unchanged. These bytes are inert test data,
not a browser-equivalence claim or permission to send.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.cf7_candidate_contract import CF7Candidate, digest
from app.services.cf7_candidate_contract import wire as base_wire
from app.services.form_execution_plan import FrozenContract, PlanError


class CheckboxOption(FrozenContract):
    option_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=1000)
    value: str = Field(min_length=1, max_length=200)
    initially_checked: bool
    disabled: Literal[False] = False

    @model_validator(mode="after")
    def safe_text(self) -> CheckboxOption:
        if not self.label.strip() or re.search(r"[\x00-\x1f\x7f]", self.label + self.value):
            raise ValueError("Explicit label and inert single-line value required")
        return self


class OptionChoice(FrozenContract):
    option_id: str
    checked: bool


class CheckboxGroup(FrozenContract):
    group_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,97}\[\]$")
    label: str = Field(min_length=1, max_length=1000)
    purpose: Literal["BUSINESS_SELECTION"]
    required: bool
    min_selected: int = Field(ge=0, le=50)
    max_selected: int = Field(ge=1, le=50)
    options: tuple[CheckboxOption, ...] = Field(min_length=1, max_length=50)
    choices: tuple[OptionChoice, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def explicit_choices(self) -> CheckboxGroup:
        if not self.label.strip() or re.search(r"[\x00-\x1f\x7f]", self.label):
            raise ValueError("Explicit group meaning required")
        ids = [option.option_id for option in self.options]
        values = [option.value for option in self.options]
        if len(set(ids)) != len(ids) or len(set(values)) != len(values):
            raise ValueError("Ambiguous option identity or value")
        if [choice.option_id for choice in self.choices] != ids:
            raise ValueError("Every option needs an explicit choice in declared order")
        if self.required != (
            self.min_selected > 0
        ) or not self.min_selected <= self.max_selected <= len(self.options):
            raise ValueError("Inconsistent group cardinality")
        selected = sum(choice.checked for choice in self.choices)
        if not self.min_selected <= selected <= self.max_selected:
            raise ValueError("Selection outside group cardinality")
        return self


class GroupCandidate(FrozenContract):
    contract_version: Literal["cf7-checkbox-groups-lab-v1"] = "cf7-checkbox-groups-lab-v1"
    canonicalization_version: Literal["cf7-groups-json-v1"] = "cf7-groups-json-v1"
    wire_order: Literal["base-then-groups-option-order-v1"] = "base-then-groups-option-order-v1"
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    source_kind: Literal["CONTROLLED_FIXTURE"]
    execution_allowed: Literal[False] = False
    eligible_for_approval: Literal[False] = False
    base: CF7Candidate
    groups: tuple[CheckboxGroup, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def binding(self) -> GroupCandidate:
        if (
            self.base.form_url != "https://managed.example/contact/"
            or self.base.rest_root != "https://managed.example/wp-json/"
        ):
            raise ValueError("Only the named managed fixture is supported")
        names = [group.name for group in self.groups]
        ids = [group.group_id for group in self.groups]
        if len(set(names)) != len(names) or len(set(ids)) != len(ids):
            raise ValueError("Duplicate group identity or name")
        scalar_names = {control.name for control in self.base.controls} | {
            value.name for value in self.base.hidden
        }
        if any(name in scalar_names or name[:-2] in scalar_names for name in names):
            raise ValueError("Group name conflicts with scalar or hidden field")
        if sum(len(group.options) for group in self.groups) > 50:
            raise ValueError("Option budget exceeded")
        selected_size = sum(
            len(option.value.encode("utf-8"))
            for group in self.groups
            for option, choice in zip(group.options, group.choices, strict=True)
            if choice.checked
        )
        base_size = sum(
            len(value.value.encode("utf-8"))
            for value in (*self.base.hidden, *self.base.field_values)
        )
        if base_size + selected_size > 40000:
            raise ValueError("Combined payload too large")
        return self


def canonical(candidate: GroupCandidate) -> dict[str, Any]:
    # Revalidate even model_construct/model_copy, including nested objects.
    candidate = GroupCandidate.model_validate(candidate.model_dump(mode="python"))
    return candidate.model_dump(mode="json")


def wire(candidate: GroupCandidate) -> tuple[str, bytes]:
    data = canonical(candidate)
    candidate = GroupCandidate.model_validate_json(json.dumps(data))
    content_type, body = base_wire(candidate.base)
    old_boundary = content_type.split("boundary=", 1)[1].encode("ascii")
    boundary = ("----LeadHiveCF7Groups" + digest(data)[:32]).encode("ascii")
    if boundary in body:
        raise PlanError("Multipart boundary collision")
    trailer = b"--" + old_boundary + b"--\r\n"
    if not body.endswith(trailer):
        raise PlanError("Unexpected base multipart framing")
    chunks = [body[: -len(trailer)].replace(old_boundary, boundary)]
    for group in candidate.groups:
        for option, choice in zip(group.options, group.choices, strict=True):
            if not choice.checked:
                continue
            value = option.value.encode("utf-8")
            if boundary in value:
                raise PlanError("Multipart boundary collision")
            chunks.append(
                b"--"
                + boundary
                + b'\r\nContent-Disposition: form-data; name="'
                + group.name.encode("ascii")
                + b'"\r\n\r\n'
                + value
                + b"\r\n"
            )
    chunks.append(b"--" + boundary + b"--\r\n")
    result = b"".join(chunks)
    if len(result) > 65536:
        raise PlanError("Multipart too large")
    return "multipart/form-data; boundary=" + boundary.decode("ascii"), result


def snapshot(candidate: GroupCandidate) -> dict[str, Any]:
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
    saved: dict[str, Any],
    current: GroupCandidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    if type(expected_version) is not int or expected_version < 1:
        raise PlanError("Invalid expected version")
    parsed = GroupCandidate.model_validate_json(json.dumps(saved.get("contract")))
    if (
        saved != snapshot(parsed)
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
        raise PlanError("Group proposal changed; a new preparation is required")
