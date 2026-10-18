"""OperationJob lease loop dedicated to safe synthetic browser analysis."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.model_operations import OperationJob
from app.runtime_version import RUNTIME_COMMIT, WORKER_HOST

logger = logging.getLogger("leadhive.browser_worker")
POLL_SECONDS = 2
LEASE_RENEW_SECONDS = 20


def _deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.worker_lease_seconds)


def recover_stale_browser_jobs(db) -> tuple[int, int]:
    jobs = db.scalars(
        select(OperationJob)
        .where(
            OperationJob.operation_type == "browser_form_analysis",
            OperationJob.status == "running",
            OperationJob.lease_expires_at < datetime.now(timezone.utc),
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    retried = failed = 0
    for job in jobs:
        job.worker_id = None
        job.lease_expires_at = None
        if job.cancel_requested:
            job.status = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
        elif job.attempt_count >= settings.worker_max_attempts:
            job.status = "failed"
            job.error_message = "ブラウザ解析ワーカー停止後の再試行回数が上限に達しました。"
            job.finished_at = datetime.now(timezone.utc)
            failed += 1
        else:
            job.status = "queued"
            job.started_at = None
            job.processed_count = job.success_count = job.failed_count = 0
            job.error_message = "ブラウザ解析ワーカー停止を検出したため再試行します。"
            retried += 1
    if jobs:
        db.commit()
    return retried, failed


def claim_browser_job(db) -> OperationJob | None:
    job = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.operation_type == "browser_form_analysis",
            OperationJob.status == "queued",
        )
        .order_by(OperationJob.created_at, OperationJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    worker_id = uuid.uuid4()
    job.status = "running"
    job.attempt_count += 1
    job.worker_id = worker_id
    job.lease_expires_at = _deadline()
    job.started_at = datetime.now(timezone.utc)
    job.finished_at = None
    job.error_message = ""
    job.payload = {
        **(job.payload or {}),
        "executed_by_commit": RUNTIME_COMMIT,
        "executed_by_host": WORKER_HOST,
    }
    db.commit()
    db.refresh(job)
    return job


def _cancel_or_renew(job_id: uuid.UUID, worker_id: uuid.UUID) -> bool:
    with SessionLocal() as db:
        job = db.scalar(select(OperationJob).where(OperationJob.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.worker_id != worker_id:
            return True
        if job.cancel_requested:
            return True
        job.lease_expires_at = _deadline()
        db.commit()
        return False


def _finish(job_id: uuid.UUID, worker_id: uuid.UUID, *, result=None, error: str = "") -> None:
    with SessionLocal() as db:
        job = db.scalar(select(OperationJob).where(OperationJob.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.worker_id != worker_id:
            return
        if job.cancel_requested:
            job.status = "cancelled"
            job.error_message = "キャンセルされました。"
        elif error:
            job.status = "failed"
            job.error_message = error[:500]
            job.processed_count = 1
            job.failed_count = 1
        else:
            job.status = "completed"
            job.processed_count = 1
            job.success_count = 1
            job.payload = {
                **(job.payload or {}),
                "synthetic_result": {
                    "fixture": result.fixture,
                    "values": result.values,
                    "blocked_request_count": result.blocked_request_count,
                    "blocked_websocket_count": result.blocked_websocket_count,
                    "blocked_popup_count": result.blocked_popup_count,
                    "blocked_file_chooser_count": result.blocked_file_chooser_count,
                    "blocked_download_count": result.blocked_download_count,
                },
            }
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(timezone.utc)
        db.commit()


def run_claimed_browser_job(job: OperationJob) -> None:
    from browser_worker.runtime import (
        BrowserTaskCancelled,
        BrowserWorkerError,
        SyntheticFormTask,
        run_synthetic_task,
    )

    worker_id = job.worker_id
    if worker_id is None:
        return
    last_check = 0.0

    def cancellation_check() -> bool:
        nonlocal last_check
        now = time.monotonic()
        if now - last_check < LEASE_RENEW_SECONDS:
            return False
        last_check = now
        return _cancel_or_renew(job.id, worker_id)

    try:
        payload = job.payload or {}
        if set(payload) - {"fixture", "fields", "executed_by_commit", "executed_by_host"}:
            raise BrowserWorkerError("Browser analysis payload contains unsupported fields.")
        task = SyntheticFormTask(fixture=payload["fixture"], fields=payload.get("fields", {}))
        result = run_synthetic_task(task, cancellation_check=cancellation_check)
    except BrowserTaskCancelled:
        _finish(job.id, worker_id, error="キャンセルされました。")
    except Exception as exc:
        logger.warning("synthetic browser analysis failed: %s", type(exc).__name__)
        _finish(job.id, worker_id, error="合成フォームの解析に失敗しました。")
    else:
        _finish(job.id, worker_id, result=result)


def run_browser_job_once() -> bool:
    if settings.worker_paused:
        return False
    with SessionLocal() as db:
        recover_stale_browser_jobs(db)
        job = claim_browser_job(db)
    if job is None:
        return False
    logger.info("synthetic browser analysis started: id=%s", job.id)
    run_claimed_browser_job(job)
    return True
