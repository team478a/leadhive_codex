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
    delivery_method: Literal["email", "form_direct", "form_codex"]
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
