"""Immutable, same-site browser form plans prepared from stored analysis only."""

import hashlib
import json
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, model_validator

from app.services.form_execution_plan import FrozenContract


class BrowserFormFieldPlan(FrozenContract):
    profile_field_id: UUID
    selector: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=500)
    field_type: str = Field(min_length=1, max_length=50)
    mapped_key: str = Field(min_length=1, max_length=50)
    value: str = Field(default="", max_length=30000)
    required: bool = False


class BrowserFormPlan(FrozenContract):
    contract_version: Literal[1] = 1
    project_id: UUID
    company_id: UUID
    source_draft_id: UUID
    form_profile_id: UUID
    form_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    form_url: str = Field(min_length=1, max_length=2000)
    action_url: str = Field(min_length=1, max_length=2000)
    form_index: int = Field(ge=0, le=100)
    method: Literal["POST"] = "POST"
    captcha_type: Literal["CAPTCHA_NONE"] = "CAPTCHA_NONE"
    same_site_only: Literal[True] = True
    confirmation_expected: bool
    submission_kind: Literal["native", "contact_form_7", "multipart", "javascript"]
    fields: tuple[BrowserFormFieldPlan, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def safe_same_site_plan(self):
        form = urlsplit(self.form_url)
        action = urlsplit(self.action_url)
        if (
            form.scheme != "https"
            or action.scheme != "https"
            or not form.hostname
            or not action.hostname
            or form.username
            or action.username
            or form.password
            or action.password
            or (form.port not in (None, 443))
            or (action.port not in (None, 443))
            or form.hostname.removeprefix("www.").casefold()
            != action.hostname.removeprefix("www.").casefold()
        ):
            raise ValueError("Browser form plans must stay on the same HTTPS site")
        names = [field.name for field in self.fields]
        selectors = [field.selector for field in self.fields]
        if len(names) != len(set(names)) or len(selectors) != len(set(selectors)):
            raise ValueError("Browser form field identities must be unique")
        if any(field.field_type == "file" for field in self.fields):
            raise ValueError("File fields are not supported")
        return self


def canonical_plan(plan: BrowserFormPlan) -> dict:
    parsed = BrowserFormPlan.model_validate(plan.model_dump(mode="python"))
    data = parsed.model_dump(mode="json")
    data["fields"] = sorted(data["fields"], key=lambda item: item["profile_field_id"])
    return data


def plan_hash(plan: BrowserFormPlan) -> str:
    encoded = json.dumps(
        canonical_plan(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
