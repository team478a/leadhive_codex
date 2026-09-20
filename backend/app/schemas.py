from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Keywords = Annotated[list[Keyword], Field(max_length=100)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    is_admin: bool
    created_at: datetime


class ProfileInput(Input):
    profile_name: Name
    description: str = Field(default="", max_length=10000)
    search_keywords: Keywords = Field(default_factory=list)
    positive_keywords: Keywords = Field(default_factory=list)
    negative_keywords: Keywords = Field(default_factory=list)
    exclusion_keywords: Keywords = Field(default_factory=list)
    scoring_rules: dict[str, JsonValue] = Field(default_factory=dict)
    ai_instruction: str = Field(default="", max_length=20000)
    default_regions: Keywords = Field(default_factory=list)
    active: bool = True


class ProfileOut(ProfileInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID | None
    is_system: bool
    created_at: datetime
    updated_at: datetime


class ProjectInput(Input):
    project_name: Name
    target_profile_id: UUID
    sales_objective: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
    ]
    region: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    status: Literal["draft", "active", "archived"] = "draft"


class ProjectOut(ProjectInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class ProjectMemberInput(Input):
    email: EmailStr
    role: Literal["editor", "viewer"]


class ProjectMemberOut(BaseModel):
    id: UUID
    project_id: UUID
    user_id: UUID
    email: str
    role: Literal["owner", "editor", "viewer"]
    created_at: datetime


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    company_name: str
    website_url: str | None
    domain: str | None
    address: str
    phone: str
    email: str
    source: Literal["serper", "google_places", "url", "csv"]
    source_keyword: str
    status: str
    notes: str
    next_followup_at: datetime | None
    assignee: str
    protected_fields: list[str]
    do_not_contact: bool
    exclusion_reason: str
    contact_quality_status: Literal["unknown", "observed", "verified", "invalid"]
    contact_source_url: str
    contact_checked_at: datetime | None
    prefecture: str
    city: str
    contact_url: str
    instagram_url: str
    x_url: str
    tiktok_url: str
    facebook_url: str
    youtube_url: str
    line_url: str
    business_summary: str
    website_text: str
    scraped_urls: list[str]
    analysis_status: str
    analysis_error: str
    is_aggregator: bool
    duplicate_of_id: UUID | None
    scraped_at: datetime | None
    score: int | None
    rank: Literal["A", "B", "C", "対象外"] | None
    is_target: bool | None
    business_type: str
    ai_summary: str
    ai_reason: str
    ai_strengths: list[str]
    ai_concerns: list[str]
    ai_recommended_approach: str
    ai_status: Literal["pending", "running", "completed", "failed", "skipped"]
    ai_error: str
    ai_provider: str
    ai_model: str
    ai_analyzed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CollectionJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    source: Literal["serper", "google_places", "url", "csv"]
    keyword: str
    region: str
    status: Literal["running", "completed", "failed"]
    found_count: int
    saved_count: int
    duplicate_count: int
    excluded_count: int
    error_count: int
    processing_ms: int
    error_message: str
    created_at: datetime
    finished_at: datetime | None


class CsvPreviewOut(BaseModel):
    headers: list[str]
    sample_rows: list[dict[str, str]]
    row_count: int
    suggested_mapping: dict[str, str]


class SearchCollectionInput(Input):
    source: Literal["serper", "google_places"]
    keywords: Annotated[list[Keyword], Field(min_length=1, max_length=20)]
    region: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    max_results: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def places_result_limit(self):
        if self.source == "google_places" and self.max_results > 60:
            raise ValueError("Google Places supports at most 60 results")
        return self


class UrlCollectionInput(Input):
    urls: Annotated[list[str], Field(min_length=1, max_length=100)]


class WebAnalysisInput(Input):
    company_ids: list[UUID] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=20, ge=1, le=20)
    force: bool = False


class CompanyAnalysisInput(Input):
    force: bool = False


class AiAnalysisInput(Input):
    company_ids: list[UUID] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=20, ge=1, le=20)
    force: bool = False


class CompanyAiAnalysisInput(Input):
    force: bool = False


class CompanySalesInput(Input):
    status: Literal[
        "unreviewed", "target", "approached", "replied", "meeting", "won", "lost", "excluded"
    ]
    notes: str = Field(default="", max_length=20000)
    next_followup_at: datetime | None = None


class CompanyEditInput(Input):
    company_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    address: str = Field(default="", max_length=5000)
    prefecture: str = Field(default="", max_length=20)
    city: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=320)
    contact_url: str = Field(default="", max_length=5000)
    instagram_url: str = Field(default="", max_length=5000)
    x_url: str = Field(default="", max_length=5000)
    tiktok_url: str = Field(default="", max_length=5000)
    facebook_url: str = Field(default="", max_length=5000)
    youtube_url: str = Field(default="", max_length=5000)
    line_url: str = Field(default="", max_length=5000)
    assignee: str = Field(default="", max_length=200)
    protected_fields: list[
        Literal[
            "company_name",
            "address",
            "prefecture",
            "city",
            "phone",
            "email",
            "contact_url",
            "instagram_url",
            "x_url",
            "tiktok_url",
            "facebook_url",
            "youtube_url",
            "line_url",
        ]
    ] = Field(default_factory=list, max_length=13)


class CompanyBulkSalesInput(Input):
    company_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    status: Literal[
        "unreviewed", "target", "approached", "replied", "meeting", "won", "lost", "excluded"
    ]


class CompanyBulkAssigneeInput(Input):
    company_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    assignee: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class CompanyContactControlInput(Input):
    do_not_contact: bool
    exclusion_reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    contact_quality_status: Literal["unknown", "observed", "verified", "invalid"] = "unknown"

    @model_validator(mode="after")
    def require_exclusion_reason(self):
        if self.do_not_contact and not self.exclusion_reason:
            raise ValueError("Do-not-contact companies require a reason")
        return self


class CompanyPageOut(BaseModel):
    items: list[CompanyOut]
    total: int
    offset: int
    limit: int


class DataQualityOut(BaseModel):
    total: int
    missing_website: int
    missing_address: int
    missing_phone: int
    missing_email: int
    missing_contact: int
    failed_analysis: int
    stale_analysis: int
    reanalyzable: int
    stale_days: int


class DataQualityReanalyzeInput(Input):
    scope: Literal["failed", "stale", "failed_or_stale"] = "failed_or_stale"
    stale_days: int = Field(default=90, ge=1, le=3650)


class DuplicateCandidateOut(BaseModel):
    left: CompanyOut
    right: CompanyOut
    reasons: list[Literal["email", "phone", "name_address"]]


class CompanyMergeInput(Input):
    target_id: UUID
    source_id: UUID


class ActivityInput(Input):
    activity_type: Literal["note", "call", "email", "form", "sns", "meeting"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    activity_type: str
    note: str
    created_at: datetime


class ContactPersonInput(Input):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    department: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=100)
    source_url: str = Field(default="", max_length=5000)
    verification_status: Literal["unknown", "verified", "invalid"] = "unknown"
    notes: str = Field(default="", max_length=10000)


class ContactPersonOut(ContactPersonInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


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


class FormPreviewOut(BaseModel):
    form_url: str
    action_url: str
    fields: list[FormFieldOut]


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
    delivery_method: Literal["direct", "codex_assisted"]
    status: Literal["pending", "submitted", "failed"]
    action_url: str
    response_status: int | None
    submitted_at: datetime | None
    error_message: str
    result_note: str
    created_at: datetime


class FormAssistOut(BaseModel):
    company_name: str
    form_url: str
    body: str
    instructions: str


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
        "followup_overdue", "operation_failed", "email_delivery_failed", "inbound_reply_received",
        "followup_due_today",
    ]
    title: str
    message: str
    read_at: datetime | None
    created_at: datetime


class OutreachQueueItemOut(BaseModel):
    company: CompanyOut
    available_channels: list[Literal["email", "form", "call", "sns"]]
    recommended_channel: Literal["email", "form", "call", "sns"]
    due_state: Literal["overdue", "today", "upcoming", "unset"]


class OutreachRecordInput(Input):
    channel: Literal["email", "form", "call", "sns"]
    outcome: Literal["approached", "replied", "meeting", "lost"] = "approached"
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    next_followup_at: datetime | None = None


class FollowupTaskOut(BaseModel):
    company: CompanyOut
    due_state: Literal["overdue", "today", "upcoming"]


class FollowupTaskResolveInput(Input):
    action: Literal["completed", "rescheduled"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    next_followup_at: datetime | None = None

    @model_validator(mode="after")
    def check_next_followup_at(self):
        if self.action == "rescheduled" and self.next_followup_at is None:
            raise ValueError("延期する場合は次回対応日時を指定してください。")
        if self.action == "completed" and self.next_followup_at is not None:
            raise ValueError("完了の場合は次回対応日時を指定できません。")
        return self


class ReplyResponseInput(Input):
    inbound_email_id: UUID
    outcome: Literal["replied", "meeting", "won", "lost"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
    next_followup_at: datetime | None = None


class ReplyQueueItemOut(BaseModel):
    company: CompanyOut
    inbound_email_id: UUID
    sender_email: str
    subject: str
    preview: str
    received_at: datetime


class OperationJobInput(Input):
    operation_type: Literal["collect_search", "web_analysis", "ai_analysis"]
    company_ids: list[UUID] = Field(default_factory=list, max_length=100)
    source: Literal["serper", "google_places"] | None = None
    keywords: list[Keyword] = Field(default_factory=list, max_length=20)
    region: str = Field(default="", max_length=500)
    max_results: int = Field(default=20, ge=1, le=100)
    force: bool = False

    @model_validator(mode="after")
    def validate_operation(self):
        if self.operation_type == "collect_search":
            if not self.source or not self.keywords or not self.region:
                raise ValueError("Search collection requires source, keywords and region")
            if self.source == "google_places" and self.max_results > 60:
                raise ValueError("Google Places supports at most 60 results")
        elif self.source or self.keywords or self.region:
            raise ValueError("Analysis operations do not accept search conditions")
        return self


class OperationJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    operation_type: str
    status: str
    total_count: int
    processed_count: int
    success_count: int
    failed_count: int
    cancel_requested: bool
    attempt_count: int
    acknowledged_at: datetime | None
    error_message: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DashboardOut(BaseModel):
    total_companies: int
    ranks: dict[str, int]
    statuses: dict[str, int]
    recent_jobs: list[CollectionJobOut]
    operation_statuses: dict[str, int]
    unread_operation_failures: int
    recent_operations: list[OperationJobOut]
    overdue_followups: int
    due_today_followups: int


class SearchScheduleInput(Input):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    source: Literal["serper", "google_places"]
    keywords: list[Keyword] = Field(min_length=1, max_length=20)
    region: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    max_results: int = Field(default=20, ge=1, le=100)
    interval_hours: int = Field(default=168, ge=1, le=720)
    company_limit: int = Field(default=10000, ge=1, le=100000)
    active: bool = True

    @model_validator(mode="after")
    def validate_places_limit(self):
        if self.source == "google_places" and self.max_results > 60:
            raise ValueError("Google Places supports at most 60 results")
        return self


class SearchScheduleOut(SearchScheduleInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    next_run_at: datetime
    last_enqueued_at: datetime | None
    last_error: str
    created_at: datetime
    updated_at: datetime


class AnalysisRefreshScheduleInput(Input):
    interval_hours: int = Field(default=168, ge=1, le=720)
    stale_days: int = Field(default=90, ge=1, le=3650)
    batch_limit: int = Field(default=100, ge=1, le=100)
    active: bool = True


class AnalysisRefreshScheduleOut(AnalysisRefreshScheduleInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    next_run_at: datetime
    last_enqueued_at: datetime | None
    last_error: str
    created_at: datetime
    updated_at: datetime


class SearchAnalyticsOut(BaseModel):
    schedule_id: UUID
    name: str
    run_count: int
    found_count: int
    saved_count: int
    duplicate_count: int
    excluded_count: int
    error_count: int
    save_rate: float
    duplicate_rate: float


class CollectionPerformanceOut(BaseModel):
    source: str
    keyword: str
    run_count: int
    found_count: int
    saved_count: int
    duplicate_count: int
    excluded_count: int
    error_count: int
    save_rate: float
    excluded_rate: float
    average_processing_ms: int


class CompanyFilterValues(Input):
    rank: str = Field(default="", max_length=20)
    minScore: str = Field(default="", max_length=3)
    region: str = Field(default="", max_length=100)
    status: str = Field(default="", max_length=30)
    source: str = Field(default="", max_length=30)
    keyword: str = Field(default="", max_length=200)
    assignee: str = Field(default="", max_length=200)
    followup: str = Field(default="", max_length=20)
    sort: str = Field(default="score_desc", max_length=30)


class SavedCompanyFilterInput(Input):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    filters: CompanyFilterValues


class SavedCompanyFilterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    name: str
    filters: dict
    created_at: datetime
    updated_at: datetime


class AssigneeAnalyticsOut(BaseModel):
    assignee: str
    total: int
    approached: int
    replied: int
    meetings: int
    won: int
    overdue: int


class SalesAnalyticsAssigneeOut(BaseModel):
    assignee: str
    approached: int
    replied: int
    meetings: int
    won: int


class SalesActivityAnalyticsOut(BaseModel):
    days: int
    activities: int
    approached: int
    replied: int
    meetings: int
    won: int
    reply_rate: float
    meeting_rate: float
    win_rate: float
    by_assignee: list[SalesAnalyticsAssigneeOut]


class OutreachEffectivenessItemOut(BaseModel):
    approval_type: Literal["email", "form_direct", "form_codex"]
    subject: str
    approvals: int
    replied: int
    meetings: int
    won: int
    reply_rate: float


class OutreachEffectivenessAnalyticsOut(BaseModel):
    days: int
    items: list[OutreachEffectivenessItemOut]
