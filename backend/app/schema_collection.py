from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from app.schema_core import Input, Keyword
from app.schema_external_presence import PresenceSearchPlan


class CollectionJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    source: Literal["serper", "google_places", "gbizinfo", "url", "csv"]
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


class CollectionDiscoveryHitOut(BaseModel):
    id: UUID
    position: int
    snapshot: dict[str, JsonValue]
    raw_hash: str
    classification: str
    classification_version: str
    classification_reason: str
    disposition: str
    company_id: UUID | None
    observed_at: datetime


class CollectionDiscoveryOut(BaseModel):
    summary: dict[str, JsonValue]
    offset: int
    limit: int
    hits: list[CollectionDiscoveryHitOut]


class CsvPreviewOut(BaseModel):
    headers: list[str]
    sample_rows: list[dict[str, str]]
    row_count: int
    suggested_mapping: dict[str, str]


class SearchCollectionInput(Input):
    presence_search: PresenceSearchPlan = Field(default_factory=PresenceSearchPlan)
    source: Literal["serper", "google_places", "gbizinfo"]
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
