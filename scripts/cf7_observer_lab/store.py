"""Unregistered O3-B persistence lab. Dedicated test DB and explicit opt-in only."""

from __future__ import annotations

import os
from datetime import timezone
from uuid import UUID

import storage_contract as contract
from app.models import (
    Company,
    FormObservationEvent,
    FormObservationEvidence,
    OperationJob,
    User,
)
from app.project_access import project_access
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session


class StoreBlocked(ValueError):
    pass


def guard(db: Session) -> None:
    if os.environ.get("CF7_OBSERVER_STORAGE_LAB") != "1":
        raise StoreBlocked("Observation storage lab disabled")
    if not str(db.scalar(text("SELECT current_database()"))).endswith("_test"):
        raise StoreBlocked("Dedicated test database required")


def source_hash(db: Session, company_id: UUID) -> str:
    return str(
        db.scalar(text("SELECT form_observation_source(:id)"), {"id": company_id})
    )


def save(
    db: Session, envelope: contract.Envelope, user: User
) -> FormObservationEvidence:
    """Stage evidence/ledger/job atomically; caller must commit or roll back.

    No acquisition/claim API. Receipts are synthetic until O3-C adds a trusted
    GET boundary. This is not reachable from the application routers/workers.
    """
    guard(db)
    # Validate BEFORE taking server identifiers from the envelope.
    try:
        envelope = contract.Envelope.model_validate(envelope)
        contract.encode(envelope)
    except (contract.ContractBlocked, ValueError):
        raise StoreBlocked("Invalid observation contract") from None
    snapshot = envelope.snapshot
    binding = snapshot.binding
    project_access(binding.project_id, db, user)
    if user.id != binding.initiated_by_user_id:
        raise HTTPException(404, "観察結果が見つかりません。")
    job = db.scalar(
        select(OperationJob)
        .where(OperationJob.id == binding.operation_job_id)
        .with_for_update()
    )
    company = db.scalar(
        select(Company).where(Company.id == binding.company_id).with_for_update()
    )
    # Lock Project/membership before rechecking rights at the persistence boundary.
    db.execute(
        text("SELECT id FROM projects WHERE id=:id FOR UPDATE"),
        {"id": binding.project_id},
    )
    db.execute(
        text(
            "SELECT id FROM project_members WHERE project_id=:p AND user_id=:u FOR SHARE"
        ),
        {"p": binding.project_id, "u": user.id},
    )
    project_access(binding.project_id, db, user)
    if (
        not job
        or not company
        or job.project_id != binding.project_id
        or company.project_id != binding.project_id
    ):
        raise StoreBlocked("Observation project binding changed")
    existing = db.scalar(
        select(FormObservationEvidence).where(
            FormObservationEvidence.operation_job_id == job.id,
            FormObservationEvidence.run_id == binding.run_id,
            FormObservationEvidence.attempt_number == binding.attempt_number,
        )
    )
    now = db.scalar(text("SELECT clock_timestamp()")).astimezone(timezone.utc)
    try:
        expected = contract.Binding.model_validate(
            binding.model_dump()
            | {
                "company_source_hash": source_hash(db, company.id),
                "target_url": company.contact_url,
                "company_project_id": company.project_id,
                "job_project_id": job.project_id,
            }
        )
    except ValueError:
        raise StoreBlocked("Current observation source changed") from None
    retired = bool(
        existing
        and db.scalar(
            select(FormObservationEvent.id).where(
                FormObservationEvent.evidence_id == existing.id,
                FormObservationEvent.event_type == "RETIRED",
            )
        )
    )
    contract.check_current(envelope, expected, now=now, retired=retired)
    if existing:
        if (
            existing.snapshot_hash != envelope.snapshot_hash
            or existing.id != snapshot.evidence_id
        ):
            raise StoreBlocked("Conflicting observation result")
        return existing
    if (
        job.operation_type != "cf7_observation"
        or job.status != "running"
        or job.cancel_requested
        or job.worker_id != binding.lease_worker_id
        or job.attempt_count != binding.attempt_number
        or not job.lease_expires_at
        or job.lease_expires_at <= now
        or job.payload
        != {
            "company_id": str(company.id),
            "run_id": str(binding.run_id),
            "initiated_by_user_id": str(user.id),
        }
    ):
        raise StoreBlocked("Observation lease or job changed")
    row = FormObservationEvidence(
        id=snapshot.evidence_id,
        project_id=company.project_id,
        company_id=company.id,
        operation_job_id=job.id,
        run_id=binding.run_id,
        attempt_number=binding.attempt_number,
        lease_worker_id=binding.lease_worker_id,
        initiated_by_user_id=user.id,
        observed_at=snapshot.observed_at,
        expires_at=snapshot.expires_at,
        snapshot=snapshot.model_dump(mode="json"),
        canonical_snapshot=contract.canonical(snapshot).decode(),
        snapshot_hash=envelope.snapshot_hash,
    )
    db.add(row)
    db.flush()
    db.add(
        FormObservationEvent(
            project_id=company.project_id,
            company_id=company.id,
            operation_job_id=job.id,
            evidence_id=row.id,
            actor_user_id=user.id,
            principal_type="SYSTEM",
            event_type="SAVED",
            reason_code="EVIDENCE_SAVED",
            snapshot_hash=row.snapshot_hash,
            created_at=now,
        )
    )
    job.status = "completed"
    job.total_count = job.processed_count = job.success_count = 1
    job.failed_count = 0
    job.worker_id = job.lease_expires_at = None
    job.finished_at = now
    db.flush()
    db.execute(text("SET CONSTRAINTS observation_saved_atomic IMMEDIATE"))
    db.execute(text("SET CONSTRAINTS observation_saved_atomic DEFERRED"))
    return row


def retire(db: Session, evidence_id: UUID, user: User, expected_hash: str) -> None:
    guard(db)
    row = db.get(FormObservationEvidence, evidence_id)
    if row is None:
        raise HTTPException(404, "観察結果が見つかりません。")
    project_access(row.project_id, db, user)
    if row.snapshot_hash != expected_hash:
        raise StoreBlocked("Observation hash changed")
    db.add(
        FormObservationEvent(
            project_id=row.project_id,
            company_id=row.company_id,
            operation_job_id=row.operation_job_id,
            evidence_id=row.id,
            actor_user_id=user.id,
            principal_type="HUMAN",
            event_type="RETIRED",
            reason_code="HUMAN_RETIRED",
            snapshot_hash=row.snapshot_hash,
            created_at=db.scalar(text("SELECT clock_timestamp()")),
        )
    )
    db.flush()
