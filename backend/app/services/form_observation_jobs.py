"""Managed-only Human queue boundary. No network, runner imports or dispatch."""

import os
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Company, FormObservationJobEvent, OperationJob, Project, ProjectMember, User
from app.project_access import company_access, project_access

FLAGS = ("CF7_OBSERVER_JOB_LAB", "CF7_OBSERVER_GET_LAB", "CF7_OBSERVER_STORAGE_LAB")
WEBSITE = "https://managed.example/"
CONTACT = "https://managed.example/contact/"


def available(db: Session) -> bool:
    return bool(db.scalar(text("SELECT to_regclass('form_observation_job_events') IS NOT NULL")))


def guard(db: Session, *, start: bool = True) -> None:
    if not available(db) or not str(db.scalar(text("SELECT current_database()"))).endswith("_test"):
        raise HTTPException(409, "管理下テスト専用の観察機能を利用できません。")
    if start and any(os.environ.get(name) != "1" for name in FLAGS):
        raise HTTPException(409, "管理下テスト専用の観察機能は無効です。")


def record(
    db: Session,
    job: OperationJob,
    event: str,
    before: str | None,
    *,
    user: User | None = None,
    reason: str,
) -> None:
    db.flush()
    db.add(
        FormObservationJobEvent(
            project_id=job.project_id,
            company_id=UUID(job.payload["company_id"]),
            operation_job_id=job.id,
            run_id=UUID(job.payload["run_id"]),
            attempt_number=job.attempt_count,
            worker_id=job.worker_id,
            actor_user_id=user.id if user else None,
            principal_type="HUMAN" if user else "SYSTEM",
            event_type=event,
            reason_code=reason,
            before_status=before,
            after_status=job.status,
        )
    )
    db.flush()


def enqueue(db: Session, company: Company, user: User) -> OperationJob:
    guard(db)
    db.execute(text("SELECT id FROM companies WHERE id=:id FOR UPDATE"), {"id": company.id})
    db.refresh(company)
    lock_rights(db, company.project_id, user)
    company_access(company.id, db, user)
    if company.website_url != WEBSITE or company.contact_url != CONTACT:
        raise HTTPException(409, "管理下テスト用URLの企業だけが対象です。")
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
    try:
        with db.begin_nested():
            db.add(job)
            record(db, job, "QUEUED", None, user=user, reason="QUEUED")
    except IntegrityError as error:
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == (
            "uq_operation_jobs_active_project_type"
        ):
            raise HTTPException(409, "同じProjectの観察ジョブが待機・実行中です。") from None
        raise
    return job


def owned_job(db: Session, job_id: UUID, user: User) -> OperationJob:
    job = db.scalar(
        select(OperationJob)
        .where(OperationJob.id == job_id, OperationJob.operation_type == "cf7_observation")
        .with_for_update()
    )
    if not job:
        raise HTTPException(404, "観察ジョブが見つかりません。")
    project_access(job.project_id, db, user)
    return job


def lock_rights(db: Session, project_id: UUID, user: User) -> None:
    db.scalars(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).all()
    db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).all()
    project_access(project_id, db, user)


def cancel(db: Session, job: OperationJob, user: User) -> None:
    guard(db, start=False)
    lock_rights(db, job.project_id, user)
    if job.status == "queued":
        job.status, job.cancel_requested = "cancelled", True
        job.finished_at = db.scalar(text("SELECT clock_timestamp()"))
        record(db, job, "CANCELLED", "queued", user=user, reason="CANCELLED")
    elif job.status == "running" and not job.cancel_requested:
        job.cancel_requested = True
        record(db, job, "CANCEL_REQUESTED", "running", user=user, reason="CANCELLED")


def recover(db: Session, job: OperationJob, user: User) -> None:
    guard(db, start=False)
    lock_rights(db, job.project_id, user)
    now = db.scalar(text("SELECT clock_timestamp()"))
    if job.status != "running" or (job.lease_expires_at and job.lease_expires_at > now):
        raise HTTPException(409, "失効した実行中ジョブだけ回収できます。")
    job.status = "cancelled" if job.cancel_requested else "failed"
    job.error_message = "CANCELLED" if job.cancel_requested else "WORKER_LOST"
    job.failed_count = 0 if job.cancel_requested else 1
    job.processed_count, job.finished_at = 1, now
    job.worker_id = job.lease_expires_at = None
    record(db, job, "RECOVERED", "running", user=user, reason=job.error_message)
