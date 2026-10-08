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

from app.schema_core import CompanyOut, Input


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
