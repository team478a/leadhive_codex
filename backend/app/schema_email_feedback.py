from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    delivery_id: UUID
    kind: Literal["delivered", "hard_bounce", "soft_bounce", "complaint", "unsubscribe"]
    recipient: str = Field(min_length=3, max_length=320)
    occurred_at: datetime
    message_id: str = Field(default="", max_length=400)

    @field_validator("occurred_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value


class HealthReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=500)
    expected_stopped_at: datetime
