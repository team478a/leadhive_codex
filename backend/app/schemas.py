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
    error_count: int
    error_message: str
    created_at: datetime
    finished_at: datetime | None


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


class CompanyBulkSalesInput(Input):
    company_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    status: Literal[
        "unreviewed", "target", "approached", "replied", "meeting", "won", "lost", "excluded"
    ]


class CompanyPageOut(BaseModel):
    items: list[CompanyOut]
    total: int
    offset: int
    limit: int


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


class SearchAnalyticsOut(BaseModel):
    schedule_id: UUID
    name: str
    run_count: int
    found_count: int
    saved_count: int
    duplicate_count: int
    error_count: int
    save_rate: float
    duplicate_rate: float
