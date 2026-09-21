from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.schema_core import Input


class ApplicationSettingsInput(Input):
    public_app_url: str = Field(default="", max_length=2000)
    openai_model: str = Field(default="", max_length=200)
    openai_api_key: str | None = Field(default=None, max_length=1024)
    serper_api_key: str | None = Field(default=None, max_length=1024)
    google_places_api_key: str | None = Field(default=None, max_length=1024)
    gbizinfo_api_token: str | None = Field(default=None, max_length=1024)
    gbizinfo_api_base_url: str = Field(default="", max_length=2000)


class ApplicationSettingsOut(BaseModel):
    public_app_url: str
    openai_model: str
    gbizinfo_api_base_url: str
    openai_api_key_source: Literal["database", "environment", "unset"]
    serper_api_key_source: Literal["database", "environment", "unset"]
    google_places_api_key_source: Literal["database", "environment", "unset"]
    gbizinfo_api_token_source: Literal["database", "environment", "unset"]
    settings_encryption_ready: bool
    updated_at: datetime | None


class ServiceConnectionTestOut(BaseModel):
    service: Literal["serper", "google_places", "openai", "gbizinfo"]
    ok: bool
    message: str
    checked_at: datetime


class SmtpSettingsInput(Input):
    host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    port: int = Field(ge=1, le=65535)
    username: str = Field(default="", max_length=320)
    password: str | None = Field(default=None, max_length=1024)
    from_email: EmailStr
    from_name: str = Field(default="LeadHive", max_length=200)
    use_starttls: bool = True
    timeout_seconds: float = Field(default=20, ge=1, le=120)
    max_emails_per_day: int = Field(default=100, ge=1, le=10_000)
    minimum_interval_seconds: int = Field(default=60, ge=0, le=3600)


class SmtpSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    host: str
    port: int
    username: str
    from_email: str
    from_name: str
    use_starttls: bool
    timeout_seconds: float
    max_emails_per_day: int
    minimum_interval_seconds: int
    password_configured: bool
    updated_at: datetime


class SmtpTestInput(Input):
    recipient_email: EmailStr


class InboundMailSettingsInput(Input):
    host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    port: int = Field(ge=1, le=65535)
    username: EmailStr
    password: str | None = Field(default=None, max_length=1024)
    mailbox: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ] = "INBOX"
    use_ssl: bool = True
    timeout_seconds: float = Field(default=20, ge=1, le=120)
    poll_interval_seconds: int = Field(default=300, ge=60, le=86_400)
    active: bool = False


class InboundMailSettingsOut(BaseModel):
    host: str
    port: int
    username: str
    mailbox: str
    use_ssl: bool
    timeout_seconds: float
    poll_interval_seconds: int
    active: bool
    password_configured: bool
    last_polled_at: datetime | None
    last_error: str
    updated_at: datetime


class InboundEmailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sender_email: str
    subject: str
    preview: str
    received_at: datetime
    company_id: UUID | None
    company_name: str = ""
    match_type: Literal["company_email", "contact_person", "manual", "unmatched"]
    classification: Literal["reply", "bounce", "unsubscribe", "other"]
    handled_by_user_id: UUID | None
    handled_at: datetime | None


class InboundEmailMatchInput(Input):
    company_id: UUID


class InboundEmailCompanyCandidateOut(BaseModel):
    id: UUID
    company_name: str
    domain: str | None
    email: str
    project_name: str


class InboundMailSyncOut(BaseModel):
    processed: int


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    company_id: UUID | None
    operation_job_id: UUID | None
    email_delivery_id: UUID | None
    inbound_email_id: UUID | None
    notification_type: Literal[
        "followup_overdue",
        "operation_failed",
        "email_delivery_failed",
        "inbound_reply_received",
        "followup_due_today",
    ]
    title: str
    message: str
    read_at: datetime | None
    created_at: datetime
