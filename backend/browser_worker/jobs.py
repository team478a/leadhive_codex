"""OperationJob lease loop dedicated to safe synthetic browser analysis."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, select, text

from app.config import settings
from app.database import SessionLocal, engine
from app.model_operations import OperationJob
from app.models import BrowserFormRun, BrowserFormScreenshot, Company, FormProfile
from app.runtime_version import RUNTIME_COMMIT, WORKER_HOST
from app.services.browser_form_analysis import (
    MAX_BROWSER_ANALYSIS_TARGETS,
    eligible_no_form_profile,
    save_rendered_analysis,
)
from app.services.contact_discovery import same_site

logger = logging.getLogger("leadhive.browser_worker")
POLL_SECONDS = 2
LEASE_RENEW_SECONDS = 20
_last_screenshot_cleanup: float | None = None


def _deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.worker_lease_seconds)


def cleanup_expired_screenshots(db) -> bool:
    global _last_screenshot_cleanup
    now = time.monotonic()
    if _last_screenshot_cleanup is not None and now - _last_screenshot_cleanup < 3600:
        return False
    try:
        db.execute(
            delete(BrowserFormScreenshot).where(
                BrowserFormScreenshot.created_at < datetime.now(timezone.utc) - timedelta(days=90)
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("browser screenshot retention cleanup failed: %s", type(exc).__name__)
        return False
    _last_screenshot_cleanup = now
    return True


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


@contextmanager
def _same_site_interval(site_host: str):
    lock_host = site_host.removeprefix("www.").lower()
    connection = engine.connect()
    locked = False
    try:
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:site_host))"), {"site_host": lock_host}
        )
        connection.commit()
        locked = True
        yield
    finally:
        if locked:
            try:
                connection.execute(text("SELECT pg_sleep(1)"))
                connection.commit()
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:site_host))"),
                    {"site_host": lock_host},
                )
                connection.commit()
            finally:
                connection.close()
        else:
            connection.close()


def _target_is_current(job: OperationJob, target: dict) -> bool:
    with SessionLocal() as db:
        company = db.get(Company, uuid.UUID(target["company_id"]))
        profile = db.get(FormProfile, uuid.UUID(target["profile_id"]))
        if (
            company is None
            or profile is None
            or company.project_id != job.project_id
            or company.do_not_contact
            or profile.company_id != company.id
            or profile.form_index != target["form_index"]
            or profile.analysis_source == "browser"
            or profile.sales_contact_status == "PROHIBITED"
        ):
            return False
        stored = urlsplit(profile.form_url)
        stored_url = urlunsplit(
            (stored.scheme, stored.netloc, stored.path or "/", stored.query, "")
        )
        if stored_url != target["url"]:
            return False
        is_eligible_no_form = eligible_no_form_profile(company, profile)
        is_eligible_form = profile.form_found and (
            profile.compatibility_reason_code
            in {
                "CONTACT_FORM_7",
                "MULTIPART_OR_FILE",
                "JAVASCRIPT_CONFIRMATION",
                "ASYNC_SUBMISSION",
            }
            or profile.confirmation_page is True
        )
        if not (is_eligible_no_form or is_eligible_form):
            return False
        if not same_site(company.website_url or "", target["url"]):
            return False
        return True


def _record_analysis_progress(
    job_id: uuid.UUID,
    worker_id: uuid.UUID,
    target: dict,
    *,
    success: bool,
    blocked_non_get_count: int = 0,
) -> None:
    with SessionLocal() as db:
        job = db.scalar(select(OperationJob).where(OperationJob.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.worker_id != worker_id:
            return
        job.processed_count += 1
        if success:
            job.success_count += 1
        else:
            job.failed_count += 1
        results = list((job.payload or {}).get("browser_analysis_results") or [])
        results.append(
            {
                "company_id": target["company_id"],
                "status": "completed" if success else "failed",
                "blocked_non_get_count": blocked_non_get_count,
            }
        )
        job.payload = {**(job.payload or {}), "browser_analysis_results": results}
        job.lease_expires_at = _deadline()
        db.commit()


def _finish_analysis_batch(job_id: uuid.UUID, worker_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.scalar(select(OperationJob).where(OperationJob.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.worker_id != worker_id:
            return
        if job.cancel_requested:
            job.status = "cancelled"
            job.error_message = "キャンセルされました。"
        else:
            job.status = "completed"
            if job.failed_count:
                job.error_message = f"{job.failed_count}社のブラウザ解析に失敗しました。"
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(timezone.utc)
        db.commit()


def _run_rendered_analysis_job(job: OperationJob, cancellation_check) -> None:
    from browser_worker.runtime import (
        BrowserTaskCancelled,
        RenderedPageTask,
        run_rendered_page_task,
    )

    worker_id = job.worker_id
    if worker_id is None:
        return
    payload = job.payload or {}
    targets = payload.get("targets")
    if (
        not settings.browser_form_analysis_enabled
        or not isinstance(targets, list)
        or not 1 <= len(targets) <= MAX_BROWSER_ANALYSIS_TARGETS
        or set(payload) - {"mode", "targets", "executed_by_commit", "executed_by_host"}
    ):
        _finish(job.id, worker_id, error="実サイトのブラウザ解析は無効か、ジョブ形式が不正です。")
        return
    job.total_count = len(targets)
    for target in targets:
        if cancellation_check(force=True):
            _finish(job.id, worker_id, error="キャンセルされました。")
            return
        if (
            not isinstance(target, dict)
            or set(target) != {"company_id", "profile_id", "url", "site_host", "form_index"}
            or not all(
                isinstance(target[key], str)
                for key in ("company_id", "profile_id", "url", "site_host")
            )
            or not isinstance(target["form_index"], int)
        ):
            _finish(job.id, worker_id, error="ブラウザ解析対象のジョブ形式が不正です。")
            return
        if not _target_is_current(job, target):
            _record_analysis_progress(job.id, worker_id, target, success=False)
            continue
        started = time.monotonic()
        try:
            with _same_site_interval(target["site_host"]):
                rendered = run_rendered_page_task(
                    RenderedPageTask(url=target["url"], site_host=target["site_host"]),
                    cancellation_check=cancellation_check,
                )
            if not same_site(target["url"], rendered.final_url):
                raise RuntimeError("Browser navigation left the approved site.")
            if cancellation_check(force=True):
                raise BrowserTaskCancelled("Browser analysis job was cancelled.")
            with SessionLocal() as db:
                company = db.get(Company, uuid.UUID(target["company_id"]))
                profile = db.get(FormProfile, uuid.UUID(target["profile_id"]))
                if (
                    company is None
                    or profile is None
                    or company.project_id != job.project_id
                    or company.do_not_contact
                    or profile.form_index != target["form_index"]
                    or profile.form_url != target["url"]
                    or profile.analysis_source == "browser"
                    or not same_site(company.website_url or "", target["url"])
                ):
                    raise RuntimeError("Browser analysis target changed before save.")
                save_rendered_analysis(
                    db,
                    company,
                    profile.id,
                    target["url"],
                    rendered.html,
                    round((time.monotonic() - started) * 1000),
                )
                db.commit()
            _record_analysis_progress(
                job.id,
                worker_id,
                target,
                success=True,
                blocked_non_get_count=rendered.blocked_non_get_count,
            )
        except BrowserTaskCancelled:
            _finish(job.id, worker_id, error="キャンセルされました。")
            return
        except Exception as exc:
            logger.warning("rendered browser analysis failed: %s", type(exc).__name__)
            _record_analysis_progress(job.id, worker_id, target, success=False)
    _finish_analysis_batch(job.id, worker_id)


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

    def cancellation_check(*, force: bool = False) -> bool:
        nonlocal last_check
        now = time.monotonic()
        if not force and now - last_check < LEASE_RENEW_SECONDS:
            return False
        last_check = now
        return _cancel_or_renew(job.id, worker_id)

    try:
        payload = job.payload or {}
        if payload.get("mode") == "rendered_analysis":
            _run_rendered_analysis_job(job, cancellation_check)
            return
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
    with engine.connect() as lock_connection:
        acquired = lock_connection.execute(
            text("SELECT pg_try_advisory_lock(4781004)")
        ).scalar_one()
        if not acquired:
            return False
        try:
            return _run_browser_job_once_locked()
        finally:
            lock_connection.execute(text("SELECT pg_advisory_unlock(4781004)"))
            lock_connection.commit()


def _run_browser_job_once_locked() -> bool:
    with SessionLocal() as db:
        cleanup_expired_screenshots(db)
        from app.services import approved_form_worker

        if settings.browser_form_delivery_enabled:
            from app.services import approved_form

            dispatch = approved_form.claim(db, browser_form=True)
            if dispatch is not None and dispatch.status == "checking":
                claimed = {
                    "id": dispatch.id,
                    "worker_id": dispatch.worker_id,
                    "approval_id": dispatch.approval_id,
                    "payload_snapshot": deepcopy(dispatch.payload_snapshot),
                }
                db.commit()
                approved_form_worker.run_browser_form(SimpleNamespace(**claimed))
                return True
        if settings.browser_form_dry_run_enabled:
            recover_stale_dry_runs(db)
            dry_run = claim_browser_dry_run(db)
            if dry_run is not None:
                claimed_run = SimpleNamespace(
                    id=dry_run.id,
                    worker_id=dry_run.worker_id,
                    payload_snapshot=deepcopy(dry_run.payload_snapshot),
                )
                db.commit()
                approved_form_worker.run_browser_dry_run(claimed_run)
                return True
        recover_stale_browser_jobs(db)
        job = claim_browser_job(db)
    if job is None:
        return False
    logger.info("browser analysis started: id=%s", job.id)
    run_claimed_browser_job(job)
    return True


def claim_browser_dry_run(db) -> BrowserFormRun | None:
    if not settings.browser_form_dry_run_enabled:
        return None
    run = db.scalar(
        select(BrowserFormRun)
        .where(BrowserFormRun.mode == "dry_run", BrowserFormRun.status == "queued")
        .order_by(BrowserFormRun.created_at, BrowserFormRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return None
    run.status = "checking"
    run.worker_id = uuid.uuid4()
    run.lease_expires_at = _deadline()
    run.started_at = None
    db.commit()
    db.refresh(run)
    return run


def recover_stale_dry_runs(db) -> int:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(BrowserFormRun)
        .where(
            BrowserFormRun.mode == "dry_run",
            BrowserFormRun.status == "checking",
            BrowserFormRun.lease_expires_at < now,
        )
        .with_for_update(skip_locked=True)
        .limit(50)
    ).all()
    for run in rows:
        run.status, run.worker_id, run.lease_expires_at = "queued", None, None
        run.reason = "dry-runワーカー中断を検出したため再開します。"
    if rows:
        db.commit()
    return len(rows)
