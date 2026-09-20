import argparse
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.ai_routes import analyze_company_ai
from app.analysis_routes import analyze
from app.collection_routes import fail_job, save_candidates, start_job
from app.config import settings
from app.database import SessionLocal
from app.models import (
    Activity,
    AnalysisRefreshSchedule,
    Company,
    EmailDelivery,
    OperationJob,
    Project,
    SearchSchedule,
    TargetProfile,
)
from app.operation_routes import refresh_company_ids
from app.services.collection import ExternalServiceError, search_google_places, search_serper
from app.services.email_delivery import EmailDeliveryError, send_email

logger = logging.getLogger("leadhive")


def lease_deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.worker_lease_seconds)


def recover_stale_jobs(db) -> tuple[int, int]:
    jobs = db.scalars(
        select(OperationJob)
        .where(
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
            job.error_message = "ワーカー停止後の再試行回数が上限に達しました。"
            job.finished_at = datetime.now(timezone.utc)
            failed += 1
        else:
            job.status = "queued"
            job.started_at = None
            job.total_count = 0
            job.processed_count = 0
            job.success_count = 0
            job.failed_count = 0
            job.error_message = "ワーカー停止を検出したため再試行します。"
            retried += 1
    if jobs:
        db.commit()
        logger.warning("stale operations recovered: retried=%s failed=%s", retried, failed)
    return retried, failed


def recover_stale_email_deliveries(db) -> int:
    deliveries = db.scalars(
        select(EmailDelivery)
        .where(
            EmailDelivery.status == "running",
            EmailDelivery.lease_expires_at < datetime.now(timezone.utc),
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    for delivery in deliveries:
        delivery.status = "failed"
        delivery.worker_id = None
        delivery.lease_expires_at = None
        delivery.error_message = "送信中断を検出しました。内容を確認してから再送してください。"
        delivery.finished_at = datetime.now(timezone.utc)
    if deliveries:
        db.commit()
        logger.warning("stale email deliveries marked failed: count=%s", len(deliveries))
    return len(deliveries)


def claim_email_delivery(db) -> EmailDelivery | None:
    delivery = db.scalar(
        select(EmailDelivery)
        .where(
            EmailDelivery.status == "queued",
            EmailDelivery.scheduled_for <= datetime.now(timezone.utc),
        )
        .order_by(EmailDelivery.scheduled_for, EmailDelivery.created_at, EmailDelivery.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if delivery:
        delivery.status = "running"
        delivery.attempt_count += 1
        delivery.worker_id = uuid.uuid4()
        delivery.lease_expires_at = lease_deadline()
        delivery.started_at = datetime.now(timezone.utc)
        delivery.finished_at = None
        db.commit()
        db.refresh(delivery)
    return delivery


def run_email_delivery(db, delivery: EmailDelivery) -> None:
    worker_id = delivery.worker_id
    logger.info("email delivery start: id=%s", delivery.id)
    try:
        send_email(db, str(delivery.id), delivery.recipient_email, delivery.subject, delivery.body)
        db.refresh(delivery)
        if delivery.status != "running" or delivery.worker_id != worker_id:
            return
        delivery.status = "sent"
        delivery.sent_at = datetime.now(timezone.utc)
        delivery.finished_at = delivery.sent_at
        delivery.worker_id = None
        delivery.lease_expires_at = None
        delivery.error_message = ""
        db.add(
            Activity(
                company_id=delivery.company_id,
                activity_type="email",
                note=f"メール送信: {delivery.recipient_email} / 件名: {delivery.subject}",
            )
        )
        db.commit()
        logger.info("email delivery end: id=%s status=sent", delivery.id)
    except EmailDeliveryError as exc:
        db.rollback()
        delivery = db.get(EmailDelivery, delivery.id)
        if delivery.status == "running" and delivery.worker_id == worker_id:
            delivery.status = "failed"
            delivery.error_message = exc.public_message[:500]
            delivery.worker_id = None
            delivery.lease_expires_at = None
            delivery.finished_at = datetime.now(timezone.utc)
            db.commit()
        logger.warning("email delivery error: id=%s type=%s", delivery.id, type(exc).__name__)
    except Exception as exc:
        db.rollback()
        delivery = db.get(EmailDelivery, delivery.id)
        if delivery.status == "running" and delivery.worker_id == worker_id:
            delivery.status = "failed"
            delivery.error_message = "メール送信処理に失敗しました。"
            delivery.worker_id = None
            delivery.lease_expires_at = None
            delivery.finished_at = datetime.now(timezone.utc)
            db.commit()
        logger.error("email delivery error: id=%s type=%s", delivery.id, type(exc).__name__)


def enqueue_due_schedules(db) -> int:
    now = datetime.now(timezone.utc)
    schedules = db.scalars(
        select(SearchSchedule)
        .where(SearchSchedule.active.is_(True), SearchSchedule.next_run_at <= now)
        .order_by(SearchSchedule.next_run_at)
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    enqueued = 0
    for schedule in schedules:
        schedule.next_run_at = now + timedelta(hours=schedule.interval_hours)
        active = db.scalar(
            select(OperationJob.id).where(
                OperationJob.project_id == schedule.project_id,
                OperationJob.operation_type == "collect_search",
                OperationJob.status.in_(("queued", "running")),
            )
        )
        company_count = (
            db.scalar(
                select(func.count())
                .select_from(Company)
                .where(Company.project_id == schedule.project_id)
            )
            or 0
        )
        if active:
            schedule.last_error = "前回の検索収集が実行中のため、今回の定期実行を見送りました。"
            continue
        if company_count >= schedule.company_limit:
            schedule.last_error = "企業保存上限に達したため、定期実行を見送りました。"
            continue
        db.add(
            OperationJob(
                project_id=schedule.project_id,
                operation_type="collect_search",
                payload={
                    "source": schedule.source,
                    "keywords": schedule.keywords,
                    "region": schedule.region,
                    "max_results": schedule.max_results,
                    "company_limit": schedule.company_limit,
                    "schedule_id": str(schedule.id),
                },
            )
        )
        schedule.last_enqueued_at = now
        schedule.last_error = ""
        enqueued += 1
    if schedules:
        db.commit()
    return enqueued


def enqueue_due_refresh_schedules(db) -> int:
    now = datetime.now(timezone.utc)
    schedules = db.scalars(
        select(AnalysisRefreshSchedule)
        .where(
            AnalysisRefreshSchedule.active.is_(True),
            AnalysisRefreshSchedule.next_run_at <= now,
        )
        .order_by(AnalysisRefreshSchedule.next_run_at)
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    enqueued = 0
    for schedule in schedules:
        schedule.next_run_at = now + timedelta(hours=schedule.interval_hours)
        active = db.scalar(
            select(OperationJob.id).where(
                OperationJob.project_id == schedule.project_id,
                OperationJob.operation_type == "web_analysis",
                OperationJob.status.in_(("queued", "running")),
            )
        )
        if active:
            schedule.last_error = "前回のWeb解析が実行中のため、今回の自動再解析を見送りました。"
            continue
        company_ids = refresh_company_ids(db, schedule)
        if not company_ids:
            schedule.last_error = ""
            continue
        db.add(
            OperationJob(
                project_id=schedule.project_id,
                operation_type="web_analysis",
                payload={"company_ids": [str(item) for item in company_ids], "force": True},
            )
        )
        schedule.last_enqueued_at = now
        schedule.last_error = ""
        enqueued += 1
    if schedules:
        db.commit()
    return enqueued


def claim_job(db) -> OperationJob | None:
    job = db.scalar(
        select(OperationJob)
        .where(OperationJob.status == "queued")
        .order_by(OperationJob.created_at, OperationJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job:
        job.status = "running"
        job.attempt_count += 1
        job.worker_id = uuid.uuid4()
        job.lease_expires_at = lease_deadline()
        job.started_at = datetime.now(timezone.utc)
        job.finished_at = None
        db.commit()
        db.refresh(job)
    return job


def stop_requested(db, job: OperationJob, worker_id: uuid.UUID) -> bool:
    db.refresh(job)
    if job.status != "running" or job.worker_id != worker_id:
        return True
    if job.cancel_requested:
        job.status = "cancelled"
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return True
    job.lease_expires_at = lease_deadline()
    db.commit()
    return False


def progress(db, job: OperationJob, worker_id: uuid.UUID, success: bool) -> bool:
    db.refresh(job)
    if job.status != "running" or job.worker_id != worker_id:
        return False
    job.processed_count += 1
    job.success_count += int(success)
    job.failed_count += int(not success)
    job.lease_expires_at = lease_deadline()
    db.commit()
    return True


def run_collection(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    payload = job.payload
    keywords = payload["keywords"]
    job.total_count = len(keywords)
    db.commit()
    if not payload.get("company_limit"):
        search = search_serper if payload["source"] == "serper" else search_google_places
        collections = [
            start_job(
                db,
                job.project_id,
                payload["source"],
                keyword,
                payload["region"],
                operation_job_id=job.id,
            )
            for keyword in keywords
        ]

        def fetch(keyword):
            try:
                return search(keyword, payload["region"], payload["max_results"]), None
            except ExternalServiceError as exc:
                return [], exc

        with ThreadPoolExecutor(max_workers=min(4, len(keywords))) as executor:
            results = list(executor.map(fetch, keywords))
        for keyword, collection, (candidates, error) in zip(
            keywords, collections, results, strict=True
        ):
            if stop_requested(db, job, worker_id):
                return
            if error:
                fail_job(db, collection, error.public_message)
                if not progress(db, job, worker_id, False):
                    return
            else:
                save_candidates(db, collection, candidates, keyword)
                if not progress(db, job, worker_id, True):
                    return
        return
    for keyword in keywords:
        if stop_requested(db, job, worker_id):
            return
        company_limit = payload.get("company_limit")
        if company_limit:
            company_count = (
                db.scalar(
                    select(func.count())
                    .select_from(Company)
                    .where(Company.project_id == job.project_id)
                )
                or 0
            )
            if company_count >= company_limit:
                job.total_count = job.processed_count
                db.commit()
                break
            max_results = min(payload["max_results"], company_limit - company_count)
        else:
            max_results = payload["max_results"]
        schedule_id = uuid.UUID(payload["schedule_id"]) if payload.get("schedule_id") else None
        collection = start_job(
            db,
            job.project_id,
            payload["source"],
            keyword,
            payload["region"],
            operation_job_id=job.id,
            search_schedule_id=schedule_id,
        )
        try:
            search = search_serper if payload["source"] == "serper" else search_google_places
            candidates = search(keyword, payload["region"], max_results)
            save_candidates(db, collection, candidates, keyword)
            if not progress(db, job, worker_id, True):
                return
        except ExternalServiceError as exc:
            fail_job(db, collection, exc.public_message)
            if not progress(db, job, worker_id, False):
                return


def selected_companies(db, job: OperationJob, ai: bool) -> list[Company]:
    payload = job.payload
    query = select(Company).where(Company.project_id == job.project_id)
    if payload.get("company_ids"):
        query = query.where(Company.id.in_(payload["company_ids"]))
    elif ai:
        query = query.where(Company.analysis_status == "completed")
        if not payload.get("force"):
            query = query.where(Company.ai_status.in_(("pending", "failed", "skipped")))
    elif not payload.get("force"):
        query = query.where(Company.analysis_status.in_(("pending", "failed")))
    return list(db.scalars(query.order_by(Company.created_at).limit(100)).all())


def run_web(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    companies = selected_companies(db, job, False)
    job.total_count = len(companies)
    db.commit()
    for company in companies:
        if stop_requested(db, job, worker_id):
            return
        result = analyze(db, company, job.payload.get("force", False))
        if not progress(db, job, worker_id, result.analysis_status == "completed"):
            return


def run_ai(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    project = db.get(Project, job.project_id)
    profile = db.get(TargetProfile, project.target_profile_id)
    companies = selected_companies(db, job, True)
    job.total_count = len(companies)
    db.commit()
    for company in companies:
        if stop_requested(db, job, worker_id):
            return
        result = analyze_company_ai(db, company, project, profile, job.payload.get("force", False))
        if not progress(db, job, worker_id, result.ai_status == "completed"):
            return


def run_once() -> bool:
    with SessionLocal() as db:
        enqueue_due_schedules(db)
        enqueue_due_refresh_schedules(db)
        recover_stale_jobs(db)
        recover_stale_email_deliveries(db)
        delivery = claim_email_delivery(db)
        if delivery is not None:
            run_email_delivery(db, delivery)
            return True
        job = claim_job(db)
        if job is None:
            return False
        worker_id = job.worker_id
        logger.info("operation start: id=%s type=%s", job.id, job.operation_type)
        try:
            {"collect_search": run_collection, "web_analysis": run_web, "ai_analysis": run_ai}[
                job.operation_type
            ](db, job, worker_id)
            db.refresh(job)
            if job.status == "running" and job.worker_id == worker_id:
                job.status = "completed" if job.failed_count == 0 else "failed"
                job.error_message = "" if job.failed_count == 0 else "一部の処理に失敗しました。"
                job.worker_id = None
                job.lease_expires_at = None
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(OperationJob, job.id)
            if job.status == "running" and job.worker_id == worker_id:
                job.status = "failed"
                job.worker_id = None
                job.lease_expires_at = None
                job.error_message = "バックグラウンド処理に失敗しました。"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
            logger.error("operation error: id=%s type=%s", job.id, type(exc).__name__)
        logger.info("operation end: id=%s status=%s", job.id, job.status)
        return True


def main():
    parser = argparse.ArgumentParser(description="LeadHive background worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    while True:
        worked = run_once()
        if args.once:
            return
        if not worked:
            time.sleep(max(0.5, min(args.poll_seconds, 30)))


if __name__ == "__main__":
    main()
