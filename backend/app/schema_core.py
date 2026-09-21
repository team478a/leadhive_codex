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
    source: Literal["serper", "google_places", "gbizinfo", "url", "csv"]
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
