from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schema_core import Input

MappedKey = Literal[
    "company_name",
    "department",
    "position",
    "contact_name",
    "last_name",
    "first_name",
    "furigana",
    "email",
    "phone",
    "postal_code",
    "prefecture",
    "city",
    "address",
    "building",
    "website",
    "contact_category",
    "subject",
    "message",
    "privacy_consent",
    "newsletter_consent",
    "other",
    "unknown",
]


class FormProfileFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    form_profile_id: UUID
    position: int
    selector: str
    label: str
    name: str
    field_type: str
    required: bool
    mapped_key: MappedKey
    confidence: float
    decision_source: Literal["DOM", "RULE", "JEV", "OPENAI", "MANUAL"]
    recommended_value: str
    options: list
    placeholder: str
    aria_label: str
    surrounding_text: str
    created_at: datetime
    updated_at: datetime


class FormProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    form_url: str
    form_index: int
    form_status: Literal["UNANALYZED", "READY", "REVIEW_REQUIRED", "BLOCKED", "STALE", "ERROR"]
    sales_contact_status: Literal["ALLOWED", "PROHIBITED", "UNCERTAIN"]
    captcha_type: Literal[
        "CAPTCHA_NONE",
        "CAPTCHA_RECAPTCHA",
        "CAPTCHA_HCAPTCHA",
        "CAPTCHA_TURNSTILE",
        "CAPTCHA_OTHER",
    ]
    confirmation_page: bool | None
    is_primary: bool
    form_found: bool
    page_kind: str
    fingerprint: str
    analysis_version: str
    analysis_provider: str
    last_analyzed_at: datetime | None
    analysis_duration_ms: int
    delivery_supported: bool
    review_reason: str
    error_message: str
    created_at: datetime
    updated_at: datetime
    fields: list[FormProfileFieldOut] = Field(default_factory=list)


class FormProfileSummaryOut(BaseModel):
    company_id: UUID
    profile_id: UUID
    form_status: str
    form_found: bool
    sales_contact_status: str
    captcha_type: str
    last_analyzed_at: datetime | None


class FormAnalysisLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    form_profile_id: UUID | None
    actor_user_id: UUID | None
    event_type: str
    provider: str
    duration_ms: int
    usage: dict
    estimated_cost: float | None
    confidence: float | None
    details: dict
    created_at: datetime


class FormFieldCorrectionInput(Input):
    mapped_key: MappedKey
    recommended_value: str = Field(default="", max_length=500)
    reason: str = Field(default="", max_length=1000)


class FormIntelligenceJobInput(Input):
    company_ids: list[UUID] = Field(default_factory=list, min_length=1, max_length=100)
    force: bool = False
