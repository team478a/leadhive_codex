"""Read-only diagnostics. These records never grant approval or sending permission."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FormObservationEvent, FormObservationEvidence, OperationJob, User
from app.project_access import company_access
from app.security import current_user
from app.services.form_observation_projection import (
    ObservationOut,
    project_record,
    storage_available,
)

router = APIRouter(prefix="/api")


class JobSummary(BaseModel):
    id: UUID
    status: str
    processed_count: int
    success_count: int
    failed_count: int


class ObservationPage(BaseModel):
    available: bool
    items: list[ObservationOut]
    has_more: bool = False
    latest_job: JobSummary | None = None


@router.get("/companies/{company_id}/form-observations", response_model=ObservationPage)
def list_observations(
    company_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = company_access(company_id, db, user, write=False)
    if not storage_available(db):
        return ObservationPage(available=False, items=[])
    retired = exists().where(
        FormObservationEvent.evidence_id == FormObservationEvidence.id,
        FormObservationEvent.event_type == "RETIRED",
    )
    rows = db.execute(
        select(FormObservationEvidence, retired)
        .where(
            FormObservationEvidence.company_id == company.id,
            FormObservationEvidence.project_id == company.project_id,
        )
        .order_by(FormObservationEvidence.observed_at.desc(), FormObservationEvidence.id.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    source_hash = db.scalar(text("SELECT form_observation_source(:id)"), {"id": company.id})
    now = db.scalar(text("SELECT clock_timestamp()"))
    latest = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == company.project_id,
            OperationJob.operation_type == "cf7_observation",
            OperationJob.payload["company_id"].astext == str(company.id),
        )
        .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
        .limit(1)
    )
    return ObservationPage(
        available=True,
        has_more=len(rows) > limit,
        items=[
            project_record(row, retired=bool(is_retired), source_hash=source_hash, now=now)
            for row, is_retired in rows[:limit]
        ],
        latest_job=JobSummary(
            id=latest.id,
            status=latest.status,
            processed_count=latest.processed_count,
            success_count=latest.success_count,
            failed_count=latest.failed_count,
        )
        if latest
        else None,
    )
