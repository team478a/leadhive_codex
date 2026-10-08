"""Human managed-lab queue/status/cancel/recovery. Never starts network execution."""

import os
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FormObservationJobEvent, OperationJob, User
from app.project_access import company_access, project_access
from app.schema_form_observation_job import REASONS, Reason
from app.security import current_user
from app.services import form_observation_jobs as service

router = APIRouter(prefix="/api")
Status = Literal["queued", "running", "completed", "failed", "cancelled"]


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: Literal[
        "QUEUED", "CLAIMED", "CANCEL_REQUESTED", "CANCELLED", "COMPLETED", "FAILED", "RECOVERED"
    ]
    reason_code: Reason
    principal_type: Literal["HUMAN", "SYSTEM"]
    before_status: Status | None
    after_status: Status
    created_at: datetime


class JobOut(BaseModel):
    id: UUID
    status: Status
    cancel_requested: bool
    recoverable: bool
    reason_code: Reason | None
    processed_count: int
    success_count: int
    failed_count: int
    events: list[EventOut]
    events_has_more: bool
    execution_allowed: Literal[False] = False


class Page(BaseModel):
    available: bool
    can_start: bool = False
    can_manage: bool = False
    items: list[JobOut] = []
    has_more: bool = False


def project_job(db: Session, job: OperationJob) -> JobOut:
    events = db.scalars(
        select(FormObservationJobEvent)
        .where(
            FormObservationJobEvent.operation_job_id == job.id,
            FormObservationJobEvent.project_id == job.project_id,
        )
        .order_by(FormObservationJobEvent.created_at.desc(), FormObservationJobEvent.id.desc())
        .limit(51)
    ).all()
    now = db.scalar(text("SELECT clock_timestamp()"))
    reason = cast(Reason, job.error_message) if job.error_message in REASONS else None
    return JobOut(
        id=job.id,
        status=cast(Status, job.status),
        cancel_requested=job.cancel_requested,
        recoverable=job.status == "running"
        and (not job.lease_expires_at or job.lease_expires_at <= now),
        reason_code=reason,
        processed_count=job.processed_count,
        success_count=job.success_count,
        failed_count=job.failed_count,
        events=[EventOut.model_validate(row) for row in events[:50]],
        events_has_more=len(events) > 50,
    )


@router.get("/companies/{company_id}/form-observation-jobs", response_model=Page)
def list_jobs(
    company_id: UUID,
    limit: int = Query(5, ge=1, le=20),
    offset: int = Query(0, ge=0, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = company_access(company_id, db, user, write=False)
    if not service.available(db):
        return Page(available=False)
    can_manage = False
    try:
        project_access(company.project_id, db, user)
        service.guard(db, start=False)
        can_manage = True
    except HTTPException:
        pass
    rows = db.scalars(
        select(OperationJob)
        .where(
            OperationJob.project_id == company.project_id,
            OperationJob.operation_type == "cf7_observation",
            OperationJob.payload["company_id"].astext == str(company.id),
        )
        .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    can_start = (
        can_manage
        and all(os.environ.get(name) == "1" for name in service.FLAGS)
        and company.website_url == service.WEBSITE
        and company.contact_url == service.CONTACT
    )
    return Page(
        available=True,
        can_manage=can_manage,
        can_start=can_start,
        items=[project_job(db, row) for row in rows[:limit]],
        has_more=len(rows) > limit,
    )


@router.post(
    "/companies/{company_id}/form-observation-jobs", response_model=JobOut, status_code=202
)
def start_job(
    company_id: UUID,
    body: EmptyInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = company_access(company_id, db, user)
    job = service.enqueue(db, company, user)
    db.commit()
    return project_job(db, job)


@router.post("/form-observation-jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: UUID,
    body: EmptyInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    job = service.owned_job(db, job_id, user)
    service.cancel(db, job, user)
    db.commit()
    return project_job(db, job)


@router.post("/form-observation-jobs/{job_id}/recover", response_model=JobOut)
def recover_job(
    job_id: UUID,
    body: EmptyInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    job = service.owned_job(db, job_id, user)
    service.recover(db, job, user)
    db.commit()
    return project_job(db, job)
