"""Confirmed, bounded fact conditions; never instructions to a sender."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schema_core import Input, Keyword
from app.schema_external_presence import PresenceSearchPlan
from app.services.presence_platforms import DOMAINS


class CollectionCondition(Input):
    id: Keyword
    priority: Literal["MUST", "WANT", "EXCLUDE"]
    type: Literal["MEDIA_EXISTS", "OFFICIAL_SITE", "AREA", "INDUSTRY", "ACTIVE_JOB", "UNRESOLVED"]
    operator: Literal["EXISTS", "EQUALS"]
    value: Keyword

    @model_validator(mode="after")
    def supported_structure(self):
        if self.type == "MEDIA_EXISTS" and (self.operator != "EXISTS" or self.value not in DOMAINS):
            raise ValueError("媒体の存在条件には対応platformとEXISTSを指定してください。")
        if self.type == "OFFICIAL_SITE" and (
            self.operator != "EXISTS" or self.value != "OFFICIAL_SITE"
        ):
            raise ValueError("公式サイト条件はEXISTS / OFFICIAL_SITEを指定してください。")
        if self.type not in {"MEDIA_EXISTS", "OFFICIAL_SITE"} and self.operator != "EQUALS":
            raise ValueError("未対応の条件構文です。")
        return self


class ConfirmCollectionConditions(Input):
    conditions: list[CollectionCondition] = Field(min_length=1, max_length=20)
    expected_version: int = Field(ge=0)
    confirmed: Literal[True]
    original_request: str = Field(default="", max_length=5000)
    requested_count: int = Field(default=100, ge=1, le=1000)
    collection_job_id: UUID | None = None

    @model_validator(mode="after")
    def unique_conditions(self):
        keys = [(c.type, c.operator, c.value) for c in self.conditions]
        if len(set(keys)) != len(keys) or len({c.id for c in self.conditions}) != len(keys):
            raise ValueError("同じ条件や矛盾する優先度を重複指定できません。")
        return self


def required_presence_plan(conditions: list[CollectionCondition]) -> PresenceSearchPlan:
    """Future collection adapter boundary; validation does not start a search."""
    return PresenceSearchPlan.model_validate(
        {
            "required_platforms": [
                c.value
                for c in conditions
                if c.type == "MEDIA_EXISTS" and c.priority in {"MUST", "EXCLUDE"}
            ]
        }
    )
