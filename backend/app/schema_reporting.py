from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.schema_core import Input, Name
from app.schema_outreach import OutreachTemplateOut


class AiReviewInput(Input):
    verdict: Literal["correct", "incorrect"]
    note: str = Field(default="", max_length=5000)


class AiReviewOut(AiReviewInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    reviewer_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AiReviewAnalyticsOut(BaseModel):
    source_keyword: str
    reviewed_count: int
    correct_count: int
    accuracy_rate: float


class DealInput(Input):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    stage: Literal["lead", "proposal", "negotiation", "won", "lost"] = "lead"
    expected_amount: int = Field(default=0, ge=0, le=10_000_000_000)
    expected_close_date: date | None = None
    owner: str = Field(default="", max_length=200)
    next_step: str = Field(default="", max_length=5000)
    lost_reason: str = Field(default="", max_length=500)


class DealOut(DealInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime


class DealPipelineItemOut(DealOut):
    project_id: UUID
    company_name: str


class DealPipelineOut(BaseModel):
    total_amount: int
    by_stage: dict[str, int]
    items: list[DealPipelineItemOut]


class OutreachExperimentInput(Input):
    name: Name
    template_a_id: UUID
    template_b_id: UUID
    active: bool = True


class OutreachExperimentOut(OutreachExperimentInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime


class OutreachExperimentAssignmentOut(BaseModel):
    experiment_id: UUID
    variant: Literal["A", "B"]
    template: OutreachTemplateOut


class OutreachExperimentResultOut(BaseModel):
    variant: Literal["A", "B"]
    delivered: int
    replied: int
    meetings: int
    won: int
    reply_rate: float


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
