from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schema_collection import CollectionJobOut
from app.schema_core import CompanyOut, Input, Keyword


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
    operation_type: Literal["collect_search", "web_analysis", "ai_analysis", "form_intelligence"]
    company_ids: list[UUID] = Field(default_factory=list, max_length=100)
    source: Literal["serper", "google_places", "gbizinfo"] | None = None
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
    source: Literal["serper", "google_places", "gbizinfo"]
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
