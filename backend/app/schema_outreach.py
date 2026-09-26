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

from app.schema_core import Input, Name


class OutreachDraftGenerateInput(Input):
    channel: Literal["email", "form", "sns"]
    contact_person_id: UUID | None = None
    instruction: str = Field(default="", max_length=1000)


class OutreachDraftUpdateInput(Input):
    subject: str = Field(default="", max_length=300)
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class OutreachDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    created_by_user_id: UUID | None
    contact_person_id: UUID | None
    channel: Literal["email", "form", "sns"]
    subject: str
    body: str
    ai_provider: str
    ai_model: str
    created_at: datetime
    updated_at: datetime


class OutreachTemplateInput(Input):
    name: Name
    channel: Literal["email", "form", "sns"]
    subject: str = Field(default="", max_length=300)
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class OutreachTemplateOut(OutreachTemplateInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class OutreachTemplateApplyInput(Input):
    template_id: UUID


class OutreachDraftApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    draft_id: UUID
    approved_by_user_id: UUID | None
    approval_type: Literal["email", "form_direct", "form_codex"]
    subject: str
    body: str
    approved_at: datetime
    delivered_at: datetime | None


class EmailDeliveryCreateInput(Input):
    recipient_email: EmailStr
    scheduled_for: datetime | None = None
    confirmed: bool = False


class EmailDeliveryRetryInput(Input):
    scheduled_for: datetime | None = None
    confirmed: bool = False


class EmailDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    draft_id: UUID
    company_id: UUID
    created_by_user_id: UUID | None
    recipient_email: str
    recipient_name: str
    subject: str
    body: str
    status: Literal["queued", "running", "sent", "failed", "cancelled"]
    scheduled_for: datetime
    confirmed_at: datetime
    sent_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    error_message: str
    created_at: datetime
    updated_at: datetime


class EmailDeliveryListItemOut(EmailDeliveryOut):
    company_name: str


class EmailDeliveryListOut(BaseModel):
    items: list[EmailDeliveryListItemOut]
    queued_count: int
    running_count: int
    sent_count: int
    failed_count: int
    cancelled_count: int


class FormFieldOut(BaseModel):
    name: str
    label: str
    field_type: Literal["text", "email", "tel", "textarea", "select"]
    required: bool
    value: str
    options: list[str] = []
    mapped_key: str = "unknown"
    confidence: float = 0
    decision_source: str = ""


class FormPreviewOut(BaseModel):
    form_url: str
    action_url: str
    fields: list[FormFieldOut]
    form_profile_id: UUID | None = None
    form_status: str = "UNANALYZED"
    fingerprint: str = ""


class FormDeliveryCreateInput(Input):
    field_values: dict[str, str] = Field(default_factory=dict)
    confirmed: bool = False


class FormAssistDeliveryInput(Input):
    status: Literal["pending", "submitted", "failed"]
    note: str = Field(default="", max_length=500)
    confirmed: bool = False


class FormDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    draft_id: UUID
    company_id: UUID
    form_profile_id: UUID | None
    delivery_method: Literal["direct", "codex_assisted"]
    status: Literal["pending", "submitted", "failed"]
    action_url: str
    response_status: int | None
    submitted_at: datetime | None
    error_message: str
    result_note: str
    profile_fingerprint: str
    field_mapping_snapshot: list
    created_at: datetime


class FormAssistOut(BaseModel):
    company_name: str
    form_url: str
    body: str
    instructions: str


class EmailCampaignCreateInput(Input):
    name: Name
    template_id: UUID
    company_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    scheduled_for: datetime | None = None
    followup_days: int = Field(default=0, ge=0, le=365)
    confirmed: bool = False


class EmailCampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    template_id: UUID
    name: str
    status: Literal["queued", "paused", "completed"]
    followup_days: int
    queued_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    replied_count: int = 0
    meeting_count: int = 0
    won_count: int = 0
    created_at: datetime
    updated_at: datetime


class FormDeliveryBatchCreateInput(Input):
    template_id: UUID
    company_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]


class FormDeliveryBatchExecuteInput(Input):
    confirmed: bool = False
    limit: int = Field(default=20, ge=1, le=20)


class FormDeliveryBatchItemRetryInput(Input):
    confirmed: bool = False


class FormCodexTaskOut(BaseModel):
    item_id: UUID
    batch_id: UUID
    company_id: UUID
    company_name: str
    form_url: str
    body: str
    reason: str
    instructions: str
    codex_status: Literal["open", "running", "submitted", "failed"]
    codex_assignee: str


class FormCodexTaskUpdateInput(Input):
    status: Literal["running", "submitted", "failed"]
    note: str = Field(default="", max_length=500)
    confirmed: bool = False


class FormDeliveryBatchItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    draft_id: UUID | None
    form_delivery_id: UUID | None
    status: Literal["queued", "submitted", "failed", "manual_required", "skipped"]
    reason: str
    submitted_at: datetime | None
    created_at: datetime
    company_name: str = ""
    form_url: str = ""


class FormDeliveryBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    template_id: UUID
    status: Literal["ready", "running", "completed", "cancelled"]
    operation_job_id: UUID | None
    created_at: datetime
    updated_at: datetime
    items: list[FormDeliveryBatchItemOut] = []
