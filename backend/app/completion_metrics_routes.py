"""Human-only measurement endpoints. Reviews do not approve or send anything."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, LeadCompletionCohort, LeadReviewSession, User
from app.project_access import project_access
from app.security import current_user
from app.services.cohort_destinations import page as destination_page
from app.services.completion_metrics import create_cohort, report
from app.services.lead_identity import identity_hash


def review_hash(company):
    values = [
        identity_hash(company),
        company.email,
        company.contact_url,
        company.do_not_contact,
        company.contact_quality_status,
        company.protected_fields,
        str(company.updated_at),
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


router = APIRouter(prefix="/api")


class CohortInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID


class FinishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["CHECKED", "REVIEW", "HOLD", "BLOCKED", "ABANDONED"]


def owned_cohort(db, user, cohort_id, write=False):
    row = db.get(LeadCompletionCohort, cohort_id)
    if row is None:
        raise HTTPException(404, "集計対象が見つかりません。")
    project = project_access(row.project_id, db, user, write=write)
    return row, project


@router.get("/projects/{project_id}/completion-cohorts")
def list_cohorts(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    return [
        dict(id=c.id, name=c.name, discovered=len(c.company_ids), created_at=c.created_at)
        for c in db.scalars(
            select(LeadCompletionCohort)
            .where(LeadCompletionCohort.project_id == project_id)
            .order_by(LeadCompletionCohort.created_at.desc())
            .limit(50)
        )
    ]


@router.post("/projects/{project_id}/completion-cohorts", status_code=201)
def freeze(
    project_id: UUID,
    body: CohortInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = project_access(project_id, db, user)
    row = create_cohort(db, project, user, body.name.strip())
    return dict(
        id=row.id, name=row.name, discovered=len(row.company_ids), created_at=row.created_at
    )


@router.get("/completion-cohorts/{cohort_id}")
def read(cohort_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row, project = owned_cohort(db, user, cohort_id)
    result = report(db, row, project)
    try:
        project_access(project.id, db, user)
        result["can_review"] = True
    except HTTPException:
        result["can_review"] = False
    result["review_candidates"] = [
        dict(id=c.id, name=c.company_name)
        for c in db.scalars(
            select(Company)
            .where(
                Company.project_id == project.id, Company.id.in_([UUID(i) for i in row.company_ids])
            )
            .order_by(Company.company_name)
        )
    ]
    result["active_review"] = db.scalar(
        select(LeadReviewSession).where(
            LeadReviewSession.cohort_id == row.id,
            LeadReviewSession.user_id == user.id,
            LeadReviewSession.finished_at.is_(None),
        )
    )
    return result


@router.post("/completion-cohorts/{cohort_id}/reviews", status_code=201)
def start_review(
    cohort_id: UUID,
    body: ReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    cohort, project = owned_cohort(db, user, cohort_id, write=True)
    if str(body.company_id) not in cohort.company_ids:
        raise HTTPException(404, "集計対象に含まれていません。")
    company = db.get(Company, body.company_id)
    if company is None or company.project_id != project.id:
        raise HTTPException(404, "企業が見つかりません。")
    db.refresh(cohort, with_for_update=True)
    active = db.scalar(
        select(LeadReviewSession).where(
            LeadReviewSession.cohort_id == cohort.id,
            LeadReviewSession.user_id == user.id,
            LeadReviewSession.finished_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    if active and (now - active.started_at).total_seconds() > 14400:
        active.finished_at, active.outcome = now, "ABANDONED"
        db.flush()
        active = None
    if active:
        if active.company_id != body.company_id:
            raise HTTPException(409, "進行中のレビューを先に終了してください。")
        return active
    row = LeadReviewSession(
        cohort_id=cohort.id,
        company_id=company.id,
        user_id=user.id,
        identity_hash=review_hash(company),
        started_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/completion-reviews/{review_id}/finish")
def finish_review(
    review_id: UUID,
    body: FinishInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.scalar(
        select(LeadReviewSession).where(LeadReviewSession.id == review_id).with_for_update()
    )
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "レビューが見つかりません。")
    cohort, project = owned_cohort(db, user, row.cohort_id, write=True)
    if row.finished_at:
        if row.outcome not in {body.outcome, "STALE", "ABANDONED"}:
            raise HTTPException(409, "終了済みのレビューは変更できません。")
        return row
    now = datetime.now(timezone.utc)
    seconds = max(0, int((now - row.started_at).total_seconds()))
    company = db.get(Company, row.company_id)
    row.finished_at = now
    row.duration_seconds = seconds if seconds <= 14400 and body.outcome != "ABANDONED" else None
    row.outcome = (
        "ABANDONED"
        if seconds > 14400 or body.outcome == "ABANDONED"
        else "STALE"
        if company is None
        or company.project_id != project.id
        or review_hash(company) != row.identity_hash
        else body.outcome
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/completion-cohorts/{cohort_id}/destination-diagnostics")
def destinations(
    cohort_id: UUID,
    benchmark: bool = Query(default=False),
    offset: int = Query(default=0, ge=0, le=3000),
    limit: int = Query(default=25, ge=1, le=50),
    expected_context_hash: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    cohort, project = owned_cohort(db, user, cohort_id)
    return destination_page(db, cohort, project, offset, limit, expected_context_hash, benchmark)
