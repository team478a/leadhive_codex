from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.schema_approval import ExpectedPayload, StrictInput


class ApprovalSelection(ExpectedPayload):
    request_id: UUID


class BulkSelection(StrictInput):
    items: list[ApprovalSelection] = Field(min_length=1, max_length=500)

    @field_validator("items")
    @classmethod
    def unique_items(cls, items):
        if len({item.request_id for item in items}) != len(items):
            raise ValueError("duplicate approval")
        return items


class BulkApprove(StrictInput):
    challenge_token: str = Field(min_length=32, max_length=200)


class ApprovedBatchCreate(BulkSelection):
    items: list[ApprovalSelection] = Field(min_length=1, max_length=10000)
    name: str = Field(min_length=1, max_length=200)
    idempotency_key: UUID
    daily_limit: int = Field(default=500, ge=1, le=10000)
    hourly_limit: int = Field(default=60, ge=1, le=1000)
    scheduled_for: datetime | None = None


class DraftSelection(StrictInput):
    draft_ids: list[UUID] = Field(min_length=1, max_length=500)

    @field_validator("draft_ids")
    @classmethod
    def unique_ids(cls, ids):
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate draft")
        return ids
