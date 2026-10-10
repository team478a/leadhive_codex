"""Feedback and correction reuse Activity and protected fields; no outbound I/O."""

import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Activity, Company, User
from app.project_access import company_access
from app.schema_core import CompanyOut
from app.security import current_user
from app.services.collection_feedback import PREFIX, apply_feedback, decode

router = APIRouter(prefix="/api/companies")


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject: Literal["company", "contact_url"]
    outcome: Literal["OK", "NG", "CORRECTED"]
    expected_updated_at: datetime
    reason: Literal[
        "confirmed",
        "wrong_company",
        "wrong_industry",
        "article",
        "recruitment",
        "reservation",
        "broken_link",
        "wrong_destination",
        "other",
    ]
    corrected_url: str = Field(default="", max_length=2048)
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def check_reason(self):
        if self.outcome == "OK" and self.reason != "confirmed":
            raise ValueError("OK requires confirmed reason")
        if self.outcome != "OK" and self.reason == "confirmed":
            raise ValueError("NG/correction requires a reason")
        if self.expected_updated_at.tzinfo is None:
            raise ValueError("Timezone is required")
        return self


@router.get("/{company_id}/collection-feedback")
def read_feedback(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company = company_access(company_id, db, user, write=False)
    rows = db.scalars(
        select(Activity)
        .where(Activity.company_id == company.id, Activity.note.startswith(PREFIX))
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(100)
    ).all()
    return {
        "items": [
            {**value, "current": value.get("after_updated_at") == company.updated_at.isoformat()}
            for row in rows
            if (value := decode(row.note)) is not None
        ]
    }


@router.post("/{company_id}/collection-feedback", status_code=201)
def record_feedback(
    company_id: UUID,
    body: FeedbackInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company_access(company_id, db, user)
    company = db.scalar(select(Company).where(Company.id == company_id).with_for_update())
    if company is None:
        raise HTTPException(404, "企業が見つかりません。")
    db.refresh(company)
    if company.updated_at != body.expected_updated_at:
        raise HTTPException(409, "企業情報が変更されました。再読込して確認してください。")
    before = company.contact_url
    apply_feedback(company, body.subject, body.outcome, body.corrected_url)
    now = datetime.now(timezone.utc)
    event = {
        "subject": body.subject,
        "outcome": body.outcome,
        "reason": body.reason,
        "note": body.note,
        "actor_user_id": str(user.id),
        "reviewed_at": now.isoformat(),
        "company_id": str(company.id),
        "project_id": str(company.project_id),
        "observed_name": company.company_name,
        "website_url": company.website_url,
        "before_contact_url": before,
        "after_contact_url": company.contact_url,
        "expected_updated_at": body.expected_updated_at.isoformat(),
        "after_updated_at": now.isoformat(),
    }
    company.updated_at = now
    db.add(
        Activity(
            company_id=company.id,
            activity_type="note",
            note=PREFIX + json.dumps(event, ensure_ascii=False),
        )
    )
    db.commit()
    db.refresh(company)
    return {
        "company": CompanyOut.model_validate(company),
        "feedback": event,
        "execution_allowed": False,
    }
