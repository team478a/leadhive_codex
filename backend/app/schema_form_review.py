from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictBool, field_validator

from app.schema_core import Input


class FormInputReviewInput(Input):
    expected_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_content_confirmed: StrictBool

    @field_validator("input_content_confirmed")
    @classmethod
    def confirmed(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Explicit Human input confirmation required")
        return value


class FormReviewMaterialOut(BaseModel):
    material_version: Literal["form-review-v1"]
    review_only: Literal[True]
    execution_supported: Literal[False]
    human_approved: Literal[False]
    items: list[dict]
    human_review_count: int
    missing_required_values: int
    profile_id: UUID
    company_id: UUID
    profile_fingerprint: str
    source_observed_at: datetime | None
    draft_id: UUID | None
    draft_hash: str | None
    sender_settings_visible: bool
    permission_status: str
    permission_reason: str
    profile_review_reason: str
    live_form_checked: Literal[False]

    technical_diagnostic: dict
    saved_choice_structure: dict
    adapter_prerequisites: dict
