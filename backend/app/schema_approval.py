import json
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.services.form_adapter_contract import ExecutableFormPlan
from app.services.form_execution_plan import ExecutionPlan

AGENT_SCOPES = frozenset(
    {
        "collection:create",
        "collection:read",
        "job:read",
        "company:read",
        "analysis:read",
        "analysis:propose",
        "outreach:prepare",
        "outreach:read",
    }
)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentIssue(StrictInput):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(min_length=1, max_length=8)
    expires_in_days: int = Field(default=30, ge=1, le=30)

    @field_validator("scopes")
    @classmethod
    def allowed_scopes(cls, value):
        if not set(value) <= AGENT_SCOPES or len(set(value)) != len(value):
            raise ValueError("unknown or forbidden scope")
        return value


class Sender(StrictInput):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    company: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=100)


class Proposal(StrictInput):
    company_id: UUID
    channel: Literal["email", "form"]
    delivery_method: Literal[
        "email", "form_direct", "form_codex", "form_plan_fixture", "form_adapter"
    ]
    source_draft_id: UUID | None = None
    recipient: EmailStr | None = None
    form_url: HttpUrl | None = None
    form_action_url: HttpUrl | None = None
    subject: str = Field(default="", max_length=1000)
    body: str = Field(min_length=1, max_length=30000)
    sender: Sender
    field_values: dict[str, str] = Field(default_factory=dict, max_length=100)
    attachment_metadata: list[dict[str, str]] = Field(default_factory=list, max_length=10)
    expires_in_hours: int = Field(default=24, ge=1, le=24)
    execution_plan: ExecutionPlan | None = None
    adapter_plan: ExecutableFormPlan | None = None

    @field_validator("adapter_plan", mode="before")
    @classmethod
    def parse_adapter_plan(cls, value):
        if isinstance(value, dict):
            return ExecutableFormPlan.model_validate_json(json.dumps(value, default=str))
        return value

    @field_validator("execution_plan", mode="before")
    @classmethod
    def parse_plan(cls, value):
        if isinstance(value, dict):
            return ExecutionPlan.model_validate_json(json.dumps(value, default=str))
        return value

    @model_validator(mode="after")
    def valid_channel(self):
        if self.channel == "email":
            if (
                self.delivery_method != "email"
                or not self.recipient
                or self.form_url
                or self.form_action_url
            ):
                raise ValueError("email target required")
        elif self.delivery_method == "email" or not self.form_url or self.recipient:
            raise ValueError("form target required")
        if sum(len(k) + len(v) for k, v in self.field_values.items()) > 40000:
            raise ValueError("fields too large")
        if self.delivery_method == "form_plan_fixture":
            plan = self.execution_plan
            if not plan or self.channel != "form" or self.attachment_metadata:
                raise ValueError("non-executable fixture plan required")
            if (
                plan.company_id != self.company_id
                or plan.form_url != str(self.form_url)
                or plan.steps[-1].url != str(self.form_action_url)
                or plan.subject != self.subject
                or plan.body != self.body
                or {v.name: v.value for v in plan.sender} != self.sender.model_dump(mode="json")
                or {v.name: v.value for v in plan.field_values} != self.field_values
            ):
                raise ValueError("plan and proposal differ")
        elif self.execution_plan is not None:
            raise ValueError("execution plan cannot be attached to a legacy delivery method")
        if self.delivery_method == "form_adapter":
            plan = self.adapter_plan
            if not plan or not self.source_draft_id or self.attachment_metadata:
                raise ValueError("adapter plan and saved draft required")
            if (
                plan.company_id != self.company_id
                or plan.source_draft_id != self.source_draft_id
                or plan.form_url != str(self.form_url)
                or plan.steps[-1].url != str(self.form_action_url)
                or plan.subject != self.subject
                or plan.body != self.body
                or {v.name: v.value for v in plan.sender} != self.sender.model_dump(mode="json")
                or {v.name: v.value for v in plan.field_values} != self.field_values
            ):
                raise ValueError("adapter plan and proposal differ")
        elif self.adapter_plan is not None:
            raise ValueError("adapter plan requires the adapter delivery method")
        return self


class ExpectedPayload(StrictInput):
    expected_hash: str = Field(pattern="^[a-f0-9]{64}$")
    expected_version: int = Field(ge=1)


class FormPreparation(StrictInput):
    expected_preparation_hash: str = Field(pattern="^[a-f0-9]{64}$")


class Revision(Proposal):
    expected_hash: str = Field(pattern="^[a-f0-9]{64}$")
    expected_version: int = Field(ge=1)


class ChallengeVerify(StrictInput):
    challenge_token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class Approve(ExpectedPayload):
    challenge_token: str = Field(min_length=32, max_length=200)


class Decision(ExpectedPayload):
    # Do not put arbitrary user text in the security ledger.
    reason: str = Field(min_length=1, max_length=1000)
