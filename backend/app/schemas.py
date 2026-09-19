from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, JsonValue, StringConstraints

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
