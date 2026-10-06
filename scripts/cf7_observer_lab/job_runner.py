"""Owned-fixture job service. No application scheduler or normal worker hookup."""

from __future__ import annotations

import os
import ssl
from collections.abc import Callable
from datetime import timedelta
from threading import Event
from typing import Literal, cast
from uuid import UUID, uuid4

import fetch
import storage_contract as contract
import store
from app.models import Company, OperationJob, User
from app.project_access import company_access, project_access
from app.schema_form_observation_job import REASONS
from app.services.form_observation_jobs import record
from failures import ObservationFailure
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

Sessions = Callable[[], Session]


class JobStopped(ValueError):
    """Only fixed server diagnostics; never store exception repr or website text."""


def enabled(db: Session) -> None:
    store.guard(db)
    if any(
        os.environ.get(name) != "1"
        for name in (
            "CF7_OBSERVER_GET_LAB",
            "CF7_OBSERVER_JOB_LAB",
        )
    ):
        raise JobStopped("LAB_DISABLED")


def clock(db: Session):
    return db.scalar(text("SELECT clock_timestamp()"))


def enqueue(sessions: Sessions, company_id: UUID, user_id: UUID) -> UUID:
    with sessions() as db:
        enabled(db)
        user = db.get(User, user_id)
        if not user:
            raise JobStopped("PERMISSION_CHANGED")
        company = company_access(company_id, db, user)
        if (
            company.contact_url != fetch.PAGE
            or company.website_url != "https://managed.example/"
        ):
            raise JobStopped("SOURCE_CHANGED")
        job = OperationJob(
            project_id=company.project_id,
            operation_type="cf7_observation",
            total_count=1,
            payload={
                "company_id": str(company.id),
                "run_id": str(uuid4()),
                "initiated_by_user_id": str(user.id),
            },
        )
        db.add(job)
        db.flush()  # Existing unique active project/type index rejects concurrent enqueue.
        result = job.id
        record(db, job, "QUEUED", None, user=user, reason="QUEUED")
        db.commit()
        return result


def current(db: Session, job: OperationJob, worker_id: UUID) -> contract.Binding:
    enabled(db)
    now = clock(db)
    if (
        job.operation_type != "cf7_observation"
        or job.status != "running"
        or job.worker_id != worker_id
    ):
        raise JobStopped("LEASE_CHANGED")
    if job.cancel_requested:
        raise JobStopped("CANCELLED")
    if not job.lease_expires_at or job.lease_expires_at <= now:
        raise JobStopped("WORKER_LOST")
    if not isinstance(job.payload, dict) or set(job.payload) != {
        "company_id",
        "run_id",
        "initiated_by_user_id",
    }:
        raise JobStopped("BINDING_CHANGED")
    try:
        user_id = UUID(job.payload["initiated_by_user_id"])
        company_id = UUID(job.payload["company_id"])
        run_id = UUID(job.payload["run_id"])
    except (ValueError, TypeError, AttributeError):
        raise JobStopped("BINDING_CHANGED") from None
    user = db.get(User, user_id)
    company = db.get(Company, company_id)
    if not user or not company or company.project_id != job.project_id:
        raise JobStopped("BINDING_CHANGED")
    try:
        project_access(job.project_id, db, user)
    except HTTPException:
        raise JobStopped("PERMISSION_CHANGED") from None
    if (
        company.contact_url != fetch.PAGE
        or company.website_url != "https://managed.example/"
    ):
        raise JobStopped("SOURCE_CHANGED")
    return contract.Binding(
        project_id=job.project_id,
        company_project_id=company.project_id,
        job_project_id=job.project_id,
        company_id=company.id,
        operation_job_id=job.id,
        run_id=run_id,
        lease_worker_id=worker_id,
        initiated_by_user_id=user.id,
        attempt_number=job.attempt_count,
        company_source_hash=store.source_hash(db, company.id),
    )


def claim(sessions: Sessions, job_id: UUID, worker_id: UUID) -> contract.Binding | None:
    with sessions() as db:
        enabled(db)
        job = db.scalar(
            select(OperationJob)
            .where(
                OperationJob.id == job_id,
                OperationJob.operation_type == "cf7_observation",
                OperationJob.status == "queued",
            )
            .with_for_update(skip_locked=True)
        )
        if not job:
            return None
        if job.cancel_requested:
            job.status, job.finished_at = "cancelled", clock(db)
            record(db, job, "CANCELLED", "queued", reason="CANCELLED")
            db.commit()
            return None
        job.status, job.worker_id = "running", worker_id
        job.attempt_count += 1
        job.started_at = clock(db)
        job.lease_expires_at = job.started_at + timedelta(seconds=60)
        db.flush()
        try:
            binding = current(db, job, worker_id)
        except (JobStopped, store.StoreBlocked, HTTPException, ValueError):
            job.status, job.error_message = "failed", "CLAIM_REJECTED"
            job.processed_count = job.failed_count = 1
            job.finished_at = clock(db)
            job.worker_id = job.lease_expires_at = None
            record(db, job, "FAILED", "queued", reason="CLAIM_REJECTED")
            db.commit()
            return None
        record(db, job, "CLAIMED", "queued", reason="CLAIMED")
        db.commit()
        return binding


class Cancellation(Event):
    def __init__(
        self, sessions: Sessions, binding: contract.Binding, stop: Event | None = None
    ):
        super().__init__()
        self.sessions, self.binding = sessions, binding
        self.reason = "OBSERVATION_FAILED"
        self.stop = stop

    def is_set(self) -> bool:
        if self.stop is not None and self.stop.is_set():
            self.reason = "RUNNER_STOPPED"
            self.set()
        if super().is_set():
            return True
        try:
            with self.sessions() as db:
                job = db.get(OperationJob, self.binding.operation_job_id)
                if (
                    not job
                    or current(db, job, self.binding.lease_worker_id) != self.binding
                ):
                    raise JobStopped("BINDING_CHANGED")
            return False
        except (JobStopped, store.StoreBlocked, ValueError, HTTPException) as error:
            self.reason = (
                str(error)
                if isinstance(error, JobStopped) and str(error) in REASONS
                else "BINDING_CHANGED"
            )
            self.set()
            return True


def finish_failed(sessions: Sessions, binding: contract.Binding, reason: str) -> None:
    reason = reason if reason in REASONS else "OBSERVATION_FAILED"
    with sessions() as db:
        # Shutdown may have disabled flags: failure cleanup still requires the dedicated DB.
        if not str(db.scalar(text("SELECT current_database()"))).endswith("_test"):
            raise JobStopped("LAB_DISABLED")
        job = db.scalar(
            select(OperationJob)
            .where(
                OperationJob.id == binding.operation_job_id,
            )
            .with_for_update()
        )
        if (
            not job
            or job.status != "running"
            or job.operation_type != "cf7_observation"
            or job.project_id != binding.project_id
            or job.worker_id != binding.lease_worker_id
            or job.attempt_count != binding.attempt_number
            or not isinstance(job.payload, dict)
            or job.payload.get("run_id") != str(binding.run_id)
        ):
            return  # A late worker must not change its successor's state.
        if reason == "RUNNER_STOPPED":
            job.cancel_requested = True
        job.status = "cancelled" if job.cancel_requested else "failed"
        job.error_message = reason
        job.failed_count = 0 if job.cancel_requested else 1
        job.processed_count = 1
        job.finished_at = clock(db)
        job.worker_id = job.lease_expires_at = None
        record(
            db,
            job,
            "CANCELLED" if job.cancel_requested else "FAILED",
            "running",
            reason=reason,
        )
        db.commit()


def run(
    sessions: Sessions,
    binding: contract.Binding,
    *,
    context: ssl.SSLContext | None = None,
    stop: Event | None = None,
) -> UUID | None:
    """GET-only, default OFF. No DB transaction/row lock spans the network call."""
    cancelled = Cancellation(sessions, binding, stop)
    stage = "preflight"
    try:
        with sessions() as db:
            if cancelled.is_set():
                raise JobStopped(cancelled.reason)
            started = clock(db)
        stage = "fetch"
        receipt = fetch.observe_owned_page(context=context, cancelled=cancelled)
        with sessions() as db:
            if cancelled.is_set():
                raise JobStopped(cancelled.reason)
            stage = "contract"
            envelope = contract.build(
                binding,
                evidence_id=uuid4(),
                body=receipt.body,
                robots=receipt.robots,
                pinned_ips=receipt.pinned_ips,
                media_type=cast(
                    Literal["text/html", "text/html; charset=utf-8"], receipt.media_type
                ),
                started_at=started,
                observed_at=clock(db),
                now=clock(db),
            )
            user = db.get(User, binding.initiated_by_user_id)
            if not user:
                raise JobStopped("PERMISSION_CHANGED")
            stage = "persist"
            row = store.save(db, envelope, user)
            evidence_id = row.id
            job = db.get(OperationJob, binding.operation_job_id)
            if not job:
                raise JobStopped("BINDING_CHANGED")
            record(db, job, "COMPLETED", "running", reason="EVIDENCE_SAVED")
            db.commit()
            return evidence_id
    except (ValueError, HTTPException, SQLAlchemyError, OSError) as error:
        # DB, TLS, parser and source failures never expose their raw exception text.
        reason = cancelled.reason
        if reason == "OBSERVATION_FAILED":
            if isinstance(error, ObservationFailure):
                reason = error.code
            elif isinstance(error, JobStopped):
                reason = str(error) if str(error) in REASONS else "OBSERVATION_FAILED"
            elif isinstance(error, HTTPException):
                reason = "PERMISSION_CHANGED"
            elif isinstance(error, SQLAlchemyError) or stage == "persist":
                reason = "OBSERVATION_STORAGE_FAILED"
            elif stage == "contract":
                reason = "OBSERVATION_CONTRACT_INVALID"
        finish_failed(sessions, binding, reason)
        return None


def recover(sessions: Sessions) -> int:
    """Fail expired leases without requeue, retry, fetch or result fabrication."""
    with sessions() as db:
        enabled(db)
        jobs = db.scalars(
            select(OperationJob)
            .where(
                OperationJob.operation_type == "cf7_observation",
                OperationJob.status == "running",
                (OperationJob.lease_expires_at <= clock(db))
                | OperationJob.lease_expires_at.is_(None),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            job.status = "cancelled" if job.cancel_requested else "failed"
            job.error_message = "CANCELLED" if job.cancel_requested else "WORKER_LOST"
            job.failed_count = 0 if job.cancel_requested else 1
            job.processed_count = 1
            job.finished_at = clock(db)
            job.worker_id = job.lease_expires_at = None
            record(db, job, "RECOVERED", "running", reason=job.error_message)
        db.commit()
        return len(jobs)
