from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schema_core import Input


class SalesPreparationInput(Input):
    company_ids: list[UUID] = Field(default_factory=list, max_length=300)
    limit: int = Field(default=300, ge=1, le=300)
    offset: int = Field(default=0, ge=0, le=100000)
    channel: Literal["email", "form", "auto"] = "auto"
    minimum_score: int = Field(default=60, ge=0, le=100)
    max_search_requests: int = Field(default=30, ge=0, le=300)
    max_ai_requests: int = Field(default=60, ge=0, le=600)
    generate_drafts: bool = True
