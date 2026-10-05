from uuid import UUID

from pydantic import Field

from app.schema_approval import ExpectedPayload, StrictInput
from app.schema_approved_email import ApprovalSelection, BulkSelection


class FormDispatchCreate(ExpectedPayload):
    idempotency_key: UUID


class FormDispatchBulk(BulkSelection):
    items: list[ApprovalSelection] = Field(min_length=1, max_length=100)
    idempotency_key: UUID


class FormLimitsUpdate(StrictInput):
    daily_limit: int = Field(ge=1, le=1000)
    hourly_limit: int = Field(ge=1, le=100)
    minimum_interval_seconds: int = Field(ge=60, le=86400)
    site_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    paused: bool
    expected_version: int = Field(ge=1)
    password: str = Field(min_length=1, max_length=200)
