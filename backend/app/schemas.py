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
