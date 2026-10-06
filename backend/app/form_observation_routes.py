"""Read-only diagnostics. These records never grant approval or sending permission."""

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ValidationError
from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FormObservationEvent, FormObservationEvidence, OperationJob, User
from app.project_access import company_access
from app.security import current_user

router = APIRouter(prefix="/api")
Freshness = Literal["CURRENT", "EXPIRED", "SOURCE_CHANGED", "RETIRED", "INVALID"]
Reason = Literal[
    "STATIC_ONLY_UNVERIFIED",
    "SALES_PROHIBITED",
    "CAPTCHA_DETECTED",
    "STRUCTURE_REQUIRES_REVIEW",
    "INTEGRITY_INVALID",
]


class Diagnostic(BaseModel):
    decision: Literal["REVIEW_REQUIRED", "BLOCKED", "HUMAN_REQUIRED", "UNSUPPORTED"]
    sales_permission: Literal["UNCERTAIN", "PROHIBITED"]
    captcha_state: Literal["UNVERIFIED", "DETECTED"]
    eligible_for_approval: Literal[False]
    execution_allowed: Literal[False]
    source_kind: Literal["STATIC_HTML_UNVERIFIED"]
    snapshot_schema_version: Literal["observation-storage-v1"]


class ObservationOut(BaseModel):
    id: UUID
    operation_job_id: UUID
    observed_at: datetime
    expires_at: datetime
    snapshot_hash: str
    freshness: Freshness
    diagnostic: Diagnostic | None
    # Do not publish website text, form values, credentials or arbitrary stored strings.
    reason: Reason
    eligible_for_approval: Literal[False] = False
    execution_allowed: Literal[False] = False


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


def storage_available(db: Session) -> bool:
    # Older installations can use the existing company UI without a live migration.
    return bool(
        db.scalar(
            text(
                "SELECT to_regclass('form_observation_evidence') IS NOT NULL "
                "AND to_regclass('form_observation_events') IS NOT NULL "
                "AND to_regprocedure('form_observation_source(uuid)') IS NOT NULL"
            )
        )
    )


def project_record(row, *, retired: bool, source_hash: str, now: datetime) -> ObservationOut:
    diagnostic = None
    freshness: Freshness = "INVALID"
    reason: Reason = "INTEGRITY_INVALID"
    try:
        canonical = row.canonical_snapshot.encode("utf-8")
        snapshot = row.snapshot
        if len(canonical) > 32768 or hashlib.sha256(canonical).hexdigest() != row.snapshot_hash:
            raise ValueError("Integrity mismatch")
        if json.loads(canonical) != snapshot:
            raise ValueError("Projection mismatch")
        binding = snapshot["binding"]
        if any(
            binding[key] != str(value)
            for key, value in (
                ("project_id", row.project_id),
                ("company_id", row.company_id),
                ("operation_job_id", row.operation_job_id),
                ("run_id", row.run_id),
            )
        ) or snapshot["evidence_id"] != str(row.id):
            raise ValueError("Binding mismatch")
        diagnostic = Diagnostic.model_validate(snapshot)
        freshness = (
            "RETIRED"
            if retired
            else "SOURCE_CHANGED"
            if binding["company_source_hash"] != source_hash
            else "EXPIRED"
            if row.expires_at <= now
            else "CURRENT"
        )
        reason = snapshot.get("reason_code")
        if reason not in {"STATIC_ONLY_UNVERIFIED", "SALES_PROHIBITED", "CAPTCHA_DETECTED"}:
            reason = "STRUCTURE_REQUIRES_REVIEW"
    except (KeyError, TypeError, ValueError, ValidationError):
        diagnostic = None
        freshness = "INVALID"
        reason = "INTEGRITY_INVALID"
    return ObservationOut(
        id=row.id,
        operation_job_id=row.operation_job_id,
        observed_at=row.observed_at,
        expires_at=row.expires_at,
        snapshot_hash=row.snapshot_hash,
        freshness=freshness,
        diagnostic=diagnostic,
        reason=reason,
    )


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
