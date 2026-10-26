import argparse
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Thread

from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError, OperationalError

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Activity,
    AnalysisRefreshSchedule,
    CollectionJob,
    Company,
    EmailCampaign,
    EmailDelivery,
    FormAnalysisLog,
    FormDeliveryBatch,
    FormDeliveryBatchItem,
    FormDmReadinessResult,
    FormProfile,
    LeadProcessingUsage,
    Notification,
    OperationJob,
    OutreachDraftApproval,
    Project,
    SearchSchedule,
    TargetProfile,
)
from app.runtime_version import RUNTIME_COMMIT, WORKER_HOST, WORKER_INSTANCE_ID
from app.services.ai_analysis import analyze_company_ai
from app.services.application_settings import apply_application_settings
from app.services.bulk_form_delivery import process_form_batch_item
from app.services.collection import (
    ExternalServiceError,
    search_gbizinfo,
    search_google_places,
    search_serper,
)
from app.services.collection_jobs import fail_job, save_candidates, start_job
from app.services.contact_permission import evaluate_contact_permission
from app.services.email_delivery import EmailDeliveryError, email_delivery_limits, send_email
from app.services.feature_retirement import GOOGLE_PLACES_RETIREMENT_MESSAGE
from app.services.form_intelligence import analyze_company_forms
from app.services.inbound_email import sync_inbound_mail
from app.services.operations import add_operation_job, refresh_company_ids
from app.services.outbound_guard import require_legacy_form_enabled, require_outbound_enabled
from app.services.processing_usage import capture_usage, measured_search, persist_usage
from app.services.web_analysis import analyze
from app.services.worker_heartbeat import record_worker_heartbeat

logger = logging.getLogger("leadhive")
EMAIL_CLAIM_LOCK_ID = 4_781_001
HEARTBEAT_INTERVAL_SECONDS = 30
READINESS_DATABASE_RETRY_LIMIT = 4


def lease_deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=settings.worker_lease_seconds)


def _heartbeat_once() -> None:
    try:
        with SessionLocal() as db:
            record_worker_heartbeat(db, worker_type="application")
    except Exception as exc:
        logger.warning("worker heartbeat failed: %s", type(exc).__name__)


def _heartbeat_loop(stop_event: Event) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        _heartbeat_once()


def stamp_operation_runtime(job: OperationJob) -> None:
    job.payload = {
        **(job.payload or {}),
        "executed_by_commit": RUNTIME_COMMIT,
        "executed_by_host": WORKER_HOST,
        "executed_by_instance_id": WORKER_INSTANCE_ID,
    }


def notify_email_delivery_failure(db, delivery: EmailDelivery) -> None:
    """Create one actionable in-app notification for each failed send attempt."""
    if delivery.created_by_user_id is None:
        return
    company = db.get(Company, delivery.company_id)
    if company is None:
        return
    dedupe_key = f"email-delivery:{delivery.id}:{delivery.attempt_count}"
    if db.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)):
        return
    db.add(
        Notification(
            user_id=delivery.created_by_user_id,
            project_id=company.project_id,
            company_id=company.id,
            email_delivery_id=delivery.id,
            notification_type="email_delivery_failed",
            title=f"メール送信に失敗しました: {company.company_name}",
            message=(
                f"{delivery.recipient_email} / "
                f"{delivery.error_message or '企業詳細で内容を確認して再送してください。'}"
            )[:1000],
            dedupe_key=dedupe_key,
        )
    )


def recover_stale_jobs(db) -> tuple[int, int]:
    jobs = db.scalars(
        select(OperationJob)
        .where(
            OperationJob.status == "running",
            OperationJob.operation_type != "cf7_observation",
            OperationJob.operation_type != "browser_form_analysis",
            OperationJob.operation_type.in_(
                (
                    "collect_search",
                    "web_analysis",
                    "site_analysis",
                    "ai_analysis",
                    "form_intelligence",
                    "prepare_outreach",
                    "extract_articles",
                    "form_dm_readiness",
                    "form_approval_batch",
                    "bulk_template_drafts",
                    "master_site_backfill",
                    "consent_policy",
                    "form_label_rule",
                )
            )
            if not settings.outbound_enabled
            else True,
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
            if job.operation_type != "prepare_outreach":
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
    from app.model_approved_email import ApprovedEmailReservation
    from app.services.approved_email_worker import recover_stale

    approved_count = recover_stale(db)

    deliveries = db.scalars(
        select(EmailDelivery)
        .where(
            EmailDelivery.status == "running",
            ~EmailDelivery.id.in_(select(ApprovedEmailReservation.delivery_id)),
            EmailDelivery.lease_expires_at < datetime.now(timezone.utc),
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    for delivery in deliveries:
        delivery.status = "unknown"
        delivery.worker_id = None
        delivery.lease_expires_at = None
        delivery.error_message = (
            "送信中断を検出しました。結果不明のため再送せずSMTP履歴を確認してください。"
        )
        delivery.finished_at = datetime.now(timezone.utc)
        notify_email_delivery_failure(db, delivery)
    if deliveries:
        db.commit()
        logger.warning("stale email deliveries marked failed: count=%s", len(deliveries))
    return len(deliveries) + approved_count


def claim_email_delivery(db) -> EmailDelivery | None:
    from app.model_approved_email import ApprovedEmailReservation
    from app.model_email_feedback import EmailHealthState

    if settings.human_approved_email_enabled:
        from app.services.approved_email_worker import claim

        return claim(db)
    if not settings.outbound_enabled:
        return None
    from app.services.sending_window import allowed

    if not allowed(db):
        db.commit()
        return None
    now = datetime.now(timezone.utc)
    db.execute(select(func.pg_advisory_xact_lock(EMAIL_CLAIM_LOCK_ID)))
    limits = email_delivery_limits(db)
    delivery_activity_at = func.coalesce(EmailDelivery.sent_at, EmailDelivery.started_at)
    active_today = db.scalar(
        select(func.count())
        .select_from(EmailDelivery)
        .where(
            EmailDelivery.status.in_(("running", "sent")),
            delivery_activity_at >= now - timedelta(days=1),
        )
    )
    if active_today >= limits.max_emails_per_day:
        db.commit()
        return None
    if limits.minimum_interval_seconds:
        last_activity_at = db.scalar(
            select(delivery_activity_at)
            .where(
                EmailDelivery.status.in_(("running", "sent")),
                delivery_activity_at.is_not(None),
            )
            .order_by(delivery_activity_at.desc())
            .limit(1)
        )
        if last_activity_at and last_activity_at > now - timedelta(
            seconds=limits.minimum_interval_seconds
        ):
            db.commit()
            return None
    delivery = db.scalar(
        select(EmailDelivery)
        .outerjoin(EmailCampaign, EmailCampaign.id == EmailDelivery.campaign_id)
        .where(
            EmailDelivery.status == "queued",
            ~EmailDelivery.id.in_(select(ApprovedEmailReservation.delivery_id)),
            ~EmailDelivery.company_id.in_(
                select(Company.id)
                .join(EmailHealthState, EmailHealthState.project_id == Company.project_id)
                .where(EmailHealthState.paused.is_(True))
            ),
            EmailDelivery.scheduled_for <= now,
            or_(EmailDelivery.campaign_id.is_(None), EmailCampaign.status == "queued"),
        )
        .order_by(EmailDelivery.scheduled_for, EmailDelivery.created_at, EmailDelivery.id)
        .with_for_update(of=EmailDelivery, skip_locked=True)
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
    else:
        db.commit()
    return delivery


def sync_campaign_status(db, campaign_id) -> None:
    if campaign_id is None:
        return
    campaign = db.get(EmailCampaign, campaign_id)
    if campaign is None or campaign.status == "paused":
        return
    active = db.scalar(
        select(EmailDelivery.id)
        .where(
            EmailDelivery.campaign_id == campaign_id,
            EmailDelivery.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if active is None:
        campaign.status = "completed"


def delivery_body_with_unsubscribe(delivery: EmailDelivery) -> str:
    if not settings.public_app_url or not delivery.unsubscribe_token:
        return delivery.body
    url = (
        f"{settings.public_app_url.rstrip('/')}/api/public/unsubscribe/{delivery.unsubscribe_token}"
    )
    return f"{delivery.body.rstrip()}\n\n---\n今後のご案内が不要な場合: {url}"


def run_email_delivery(db, delivery: EmailDelivery) -> None:
    require_outbound_enabled()
    from app.services.sending_window import defer_email

    if defer_email(db, delivery):
        return
    from app.services.approved_email import reservation

    if reservation(db, delivery.id):
        from app.services.approved_email_worker import run

        run(db, delivery)
        return
    require_outbound_enabled()
    worker_id = delivery.worker_id
    smtp_started = False
    logger.info("email delivery start: id=%s", delivery.id)
    try:
        company = db.get(Company, delivery.company_id)
        if company is None:
            raise EmailDeliveryError("送信対象の企業が見つかりません。")
        from app.services.email_feedback import evaluate

        health, _ = evaluate(db, company.project_id)
        if health.paused:
            raise EmailDeliveryError("配信異常による安全停止中です。")
        permission = evaluate_contact_permission(
            db,
            company.project_id,
            company.id,
            "email",
            delivery.recipient_email,
        )
        if not permission.allowed:
            raise EmailDeliveryError(permission.message)
        smtp_started = True
        send_email(
            db,
            str(delivery.id),
            delivery.recipient_email,
            delivery.subject,
            delivery_body_with_unsubscribe(delivery),
        )
        db.refresh(delivery)
        if delivery.status != "running" or delivery.worker_id != worker_id:
            return
        delivery.status = "sent"
        delivery.sent_at = datetime.now(timezone.utc)
        delivery.finished_at = delivery.sent_at
        delivery.worker_id = None
        delivery.lease_expires_at = None
        delivery.error_message = ""
        approval = db.scalar(
            select(OutreachDraftApproval).where(
                OutreachDraftApproval.draft_id == delivery.draft_id,
                OutreachDraftApproval.approval_type == "email",
            )
        )
        if approval:
            approval.delivered_at = delivery.sent_at
        db.add(
            Activity(
                company_id=delivery.company_id,
                activity_type="email",
                note=f"メール送信: {delivery.recipient_email} / 件名: {delivery.subject}",
            )
        )
        company = db.get(Company, delivery.company_id)
        if company and company.status in {"unreviewed", "target"}:
            company.status = "approached"
            db.add(
                Activity(
                    company_id=company.id,
                    activity_type="status_change",
                    note="営業状況を更新: アプローチ済（メール送信）",
                )
            )
        campaign = db.get(EmailCampaign, delivery.campaign_id) if delivery.campaign_id else None
        if (
            campaign
            and campaign.followup_days
            and company
            and company.status in {"approached", "target", "unreviewed"}
        ):
            company.next_followup_at = delivery.sent_at + timedelta(days=campaign.followup_days)
            db.add(
                Activity(
                    company_id=company.id,
                    activity_type="note",
                    note=f"メールキャンペーンの追客予定を登録: {campaign.followup_days}日後",
                )
            )
        sync_campaign_status(db, delivery.campaign_id)
        db.commit()
        logger.info("email delivery end: id=%s status=sent", delivery.id)
    except EmailDeliveryError as exc:
        db.rollback()
        delivery = db.get(EmailDelivery, delivery.id)
        if delivery.status == "running" and delivery.worker_id == worker_id:
            delivery.status = "unknown" if exc.unknown else "failed"
            delivery.error_message = exc.public_message[:500]
            delivery.worker_id = None
            delivery.lease_expires_at = None
            delivery.finished_at = datetime.now(timezone.utc)
            notify_email_delivery_failure(db, delivery)
            sync_campaign_status(db, delivery.campaign_id)
            db.commit()
        logger.warning("email delivery error: id=%s type=%s", delivery.id, type(exc).__name__)
    except Exception as exc:
        db.rollback()
        delivery = db.get(EmailDelivery, delivery.id)
        if delivery.status == "running" and delivery.worker_id == worker_id:
            delivery.status = "unknown" if smtp_started else "failed"
            delivery.error_message = "メール送信処理に失敗しました。"
            delivery.worker_id = None
            delivery.lease_expires_at = None
            delivery.finished_at = datetime.now(timezone.utc)
            notify_email_delivery_failure(db, delivery)
            sync_campaign_status(db, delivery.campaign_id)
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
        if schedule.source == "google_places":
            schedule.active = False
            schedule.last_error = GOOGLE_PLACES_RETIREMENT_MESSAGE
            continue
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
        job = OperationJob(
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
        if not add_operation_job(db, job):
            schedule.last_error = "前回の検索収集が実行中のため、今回の定期実行を見送りました。"
            continue
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
                OperationJob.operation_type.in_(
                    (
                        "web_analysis",
                        "site_analysis",
                        "form_intelligence",
                        "prepare_outreach",
                    )
                ),
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
        job = OperationJob(
            project_id=schedule.project_id,
            operation_type="site_analysis",
            payload={"company_ids": [str(item) for item in company_ids], "force": True},
        )
        if not add_operation_job(db, job):
            schedule.last_error = "前回のWeb解析が実行中のため、今回の自動再解析を見送りました。"
            continue
        schedule.last_enqueued_at = now
        schedule.last_error = ""
        enqueued += 1
    if schedules:
        db.commit()
    return enqueued


def claim_job(db) -> OperationJob | None:
    from app.services.sending_window import allowed

    sending_allowed = allowed(db)
    job = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.status == "queued",
            OperationJob.operation_type != "cf7_observation",
            OperationJob.operation_type != "browser_form_analysis",
            OperationJob.operation_type != "form_delivery" if not sending_allowed else True,
            OperationJob.operation_type.in_(
                (
                    "collect_search",
                    "web_analysis",
                    "site_analysis",
                    "ai_analysis",
                    "form_intelligence",
                    "prepare_outreach",
                    "extract_articles",
                    "form_dm_readiness",
                    "form_approval_batch",
                    "bulk_template_drafts",
                    "master_site_backfill",
                    "consent_policy",
                    "form_label_rule",
                )
            )
            if not settings.outbound_enabled
            else True,
        )
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
        if job.operation_type == "collect_search":
            from app.services.collection_runtime import annotate_claim

            annotate_claim(job)
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
    from app.services.collection_conditions import evaluate
    from app.services.condition_collection import execution_conditions, merged_plan

    conditions = execution_conditions(db, job)
    payload = job.payload
    if conditions:
        payload = {
            **payload,
            "presence_search": merged_plan(conditions, payload.get("presence_search")).model_dump(),
        }
    keywords = payload["keywords"]
    if payload.get("target_count"):
        from app.services.target_collection import run

        if payload.get("query_plan"):
            from app.services.collection_scheduler import run

        job.total_count = payload["target_count"]
        db.commit()
        run(db, job, payload, conditions, lambda: stop_requested(db, job, worker_id))
        return
    job.total_count = len(keywords)
    db.commit()
    if not payload.get("company_limit") and not payload.get("presence_search"):
        search = {
            "serper": search_serper,
            "google_places": search_google_places,
            "gbizinfo": search_gbizinfo,
        }[payload["source"]]
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
            from app.services.discovery_capture import capturing_discovery

            with capture_usage() as usage, capturing_discovery() as discovery:
                try:
                    return (
                        search(keyword, payload["region"], payload["max_results"]),
                        None,
                        usage,
                        discovery,
                    )
                except ExternalServiceError as exc:
                    return [], exc, usage, discovery

        with ThreadPoolExecutor(max_workers=min(4, len(keywords))) as executor:
            results = list(executor.map(fetch, keywords))
        for keyword, collection, (candidates, error, usage, discovery) in zip(
            keywords, collections, results, strict=True
        ):
            from app.services.collection_discovery import persist_discovery

            persist_discovery(db, collection, discovery)
            persist_usage(db, usage, job.project_id, collection_job_id=collection.id)
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
        if conditions:
            execution_conditions(db, job)
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
            search = {
                "serper": search_serper,
                "google_places": search_google_places,
                "gbizinfo": search_gbizinfo,
            }[payload["source"]]
            candidates = measured_search(
                db, collection, search, keyword, payload["region"], max_results
            )
            save_candidates(db, collection, candidates, keyword)
            if payload.get("presence_search"):
                from app.schema_external_presence import PresenceSearchPlan
                from app.services.external_presence import extra_searches

                collection.presence_search_plan = payload["presence_search"]
                db.commit()
                extra_searches(
                    db,
                    collection,
                    PresenceSearchPlan.model_validate(payload["presence_search"]),
                    stopped=lambda: stop_requested(db, job, worker_id),
                    eligible=lambda company: (
                        not conditions or evaluate(db, company, conditions)["state"] != "NO_MATCH"
                    ),
                )
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
        from app.services.ai_targeting import ai_company_query

        query = ai_company_query(
            job.project_id,
            scope=payload.get("ai_target_scope", "all"),
            force=payload.get("force", False),
        )
    elif not payload.get("force"):
        query = query.where(Company.analysis_status.in_(("pending", "failed")))
    return list(db.scalars(query.order_by(Company.created_at).limit(100)).all())


def next_analysis_batch(
    db,
    job: OperationJob,
    ai: bool,
    processed_company_ids: set[uuid.UUID] | None = None,
) -> list[Company]:
    """Select eligible records not already processed by this job."""
    query = select(Company).where(Company.project_id == job.project_id)
    if ai:
        from app.services.ai_targeting import ai_company_query

        query = ai_company_query(
            job.project_id,
            scope=job.payload.get("ai_target_scope", "all"),
            force=job.payload.get("force", False),
        )
    else:
        query = query.where(
            Company.website_url.is_not(None),
            Company.analysis_status == "pending",
        )
    if processed_company_ids:
        query = query.where(Company.id.notin_(processed_company_ids))
    return list(db.scalars(query.order_by(Company.created_at, Company.id).limit(100)).all())


def run_web(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    companies = selected_companies(db, job, False)
    job.total_count = len(companies)
    db.commit()
    while companies:
        for company in companies:
            if stop_requested(db, job, worker_id):
                return
            result = analyze(db, company, job.payload.get("force", False))
            if not progress(db, job, worker_id, result.analysis_status == "completed"):
                return
        # Explicitly selected company IDs are a bounded one-off operation.
        if job.payload.get("company_ids") or job.payload.get("force"):
            return
        companies = next_analysis_batch(db, job, False)
        if companies:
            job.total_count += len(companies)
            db.commit()


def run_ai(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    project = db.get(Project, job.project_id)
    profile = db.get(TargetProfile, project.target_profile_id)
    companies = selected_companies(db, job, True)
    job.total_count = len(companies)
    db.commit()
    processed_company_ids: set[uuid.UUID] = set()
    while companies:
        for company in companies:
            if stop_requested(db, job, worker_id):
                return
            result = analyze_company_ai(
                db, company, project, profile, job.payload.get("force", False)
            )
            if not progress(db, job, worker_id, result.ai_status == "completed"):
                return
            processed_company_ids.add(company.id)
        if job.payload.get("company_ids") or job.payload.get("force"):
            return
        companies = next_analysis_batch(db, job, True, processed_company_ids)
        if companies:
            job.total_count += len(companies)
            db.commit()


def run_site_analysis(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    from app.services.scraper import PageFetchCache
    from app.services.site_analysis import analyze_site_company

    job_id = job.id
    project_id = job.project_id
    processed_ids: set[uuid.UUID] = set()
    explicit_ids = bool((job.payload or {}).get("company_ids"))

    while True:
        current = db.get(OperationJob, job_id)
        if current is None or stop_requested(db, current, worker_id):
            return
        payload = dict(current.payload or {})
        scan_unanalyzed = bool(payload.get("scan_unanalyzed") or not explicit_ids)
        company_ids = [
            uuid.UUID(value)
            for value in payload.get("company_ids", [])
            if uuid.UUID(value) not in processed_ids
        ][:100]
        if scan_unanalyzed:
            has_terminal_form_log = (
                select(FormAnalysisLog.id)
                .where(
                    FormAnalysisLog.company_id == Company.id,
                    FormAnalysisLog.event_type.in_(("analysis_completed", "analysis_failed")),
                )
                .exists()
            )
            query = select(Company.id).where(
                Company.project_id == project_id,
                Company.website_url.is_not(None),
                Company.analysis_status.notin_(("excluded", "duplicate")),
                or_(
                    Company.analysis_status.in_(("pending", "failed")),
                    ~has_terminal_form_log,
                ),
            )
            if processed_ids:
                query = query.where(Company.id.notin_(processed_ids))
            if payload.get("force"):
                query = select(Company.id).where(
                    Company.project_id == project_id,
                    Company.website_url.is_not(None),
                    Company.analysis_status.notin_(("excluded", "duplicate")),
                )
                if processed_ids:
                    query = query.where(Company.id.notin_(processed_ids))
            scan_capacity = max(0, 100 - len(company_ids))
            if scan_capacity:
                company_ids.extend(
                    company_id
                    for company_id in db.scalars(
                        query.order_by(Company.created_at, Company.id).limit(scan_capacity)
                    ).all()
                    if company_id not in company_ids
                )

        if not company_ids:
            locked = db.scalar(
                select(OperationJob).where(OperationJob.id == job_id).with_for_update()
            )
            if locked is None:
                return
            latest_ids = {
                uuid.UUID(value) for value in (locked.payload or {}).get("company_ids", [])
            }
            if latest_ids - processed_ids:
                continue
            return

        current.total_count = max(current.total_count, len(processed_ids) + len(company_ids))
        db.commit()
        for company_id in company_ids:
            if stop_requested(db, current, worker_id):
                return
            success = False
            company = db.get(Company, company_id)
            if company is not None:
                cache = PageFetchCache()
                try:
                    success = analyze_site_company(
                        db,
                        company,
                        force=bool(payload.get("force")),
                        page_cache=cache,
                    )
                except Exception as exc:
                    db.rollback()
                    logger.warning(
                        "site analysis failed: company_id=%s type=%s",
                        company_id,
                        type(exc).__name__,
                    )
                    current = db.get(OperationJob, job_id)
                    if current is None:
                        return
            if not progress(db, current, worker_id, success):
                return
            processed_ids.add(company_id)
            db.expunge_all()
            db.add(job)
            db.refresh(job)
            current = job


def run_form_delivery(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    require_legacy_form_enabled()
    batch_id = uuid.UUID(job.payload["batch_id"])
    batch = db.get(FormDeliveryBatch, batch_id)
    if batch is None or batch.status == "cancelled":
        return
    user_id = uuid.UUID(job.payload["created_by_user_id"])
    items = db.scalars(
        select(FormDeliveryBatchItem)
        .where(
            FormDeliveryBatchItem.batch_id == batch.id,
            FormDeliveryBatchItem.status == "queued",
        )
        .order_by(FormDeliveryBatchItem.created_at, FormDeliveryBatchItem.id)
        .limit(min(int(job.payload.get("limit", 20)), 20))
    ).all()
    job.total_count = len(items)
    db.commit()
    for item in items:
        if stop_requested(db, job, worker_id):
            return
        from app.services.sending_window import allowed

        if not allowed(db):
            job.status, job.worker_id, job.lease_expires_at = "queued", None, None
            db.commit()
            return
        success = process_form_batch_item(db, item, user_id)
        if not progress(db, job, worker_id, success):
            return
    remaining = db.scalar(
        select(FormDeliveryBatchItem.id)
        .where(
            FormDeliveryBatchItem.batch_id == batch.id,
            FormDeliveryBatchItem.status == "queued",
        )
        .limit(1)
    )
    batch.status = "ready" if remaining else "completed"
    db.commit()


def next_form_analysis_batch(db, project_id: uuid.UUID, force: bool = False) -> list[Company]:
    query = select(Company).where(
        Company.project_id == project_id,
        Company.analysis_status == "completed",
        Company.website_url.is_not(None),
    )
    if not force:
        has_profile = select(FormProfile.id).where(FormProfile.company_id == Company.id).exists()
        has_unanalyzed_profile = (
            select(FormProfile.id)
            .where(
                FormProfile.company_id == Company.id,
                FormProfile.form_status == "UNANALYZED",
                FormProfile.last_analyzed_at.is_(None),
            )
            .exists()
        )
        has_terminal_log = (
            select(FormAnalysisLog.id)
            .where(
                FormAnalysisLog.company_id == Company.id,
                FormAnalysisLog.event_type.in_(("analysis_completed", "analysis_failed")),
            )
            .exists()
        )
        query = query.where(
            ~has_terminal_log,
            or_(~has_profile, has_unanalyzed_profile),
        )
    return list(db.scalars(query.order_by(Company.created_at, Company.id).limit(100)).all())


def run_form_intelligence(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    company_ids = [uuid.UUID(value) for value in job.payload.get("company_ids", [])]
    if company_ids:
        pending_ids = list(dict.fromkeys(company_ids))
        job.total_count = len(pending_ids)
        db.commit()
        processed_ids = set()
        while pending_ids:
            batch_ids = pending_ids[:100]
            pending_ids = pending_ids[100:]
            companies = db.scalars(
                select(Company)
                .where(Company.project_id == job.project_id, Company.id.in_(batch_ids))
                .order_by(Company.created_at, Company.id)
            ).all()
            for company in companies:
                if stop_requested(db, job, worker_id):
                    return
                profiles = analyze_company_forms(db, company, bool(job.payload.get("force")))
                success = bool(profiles) and any(
                    profile.form_status != "ERROR" for profile in profiles
                )
                if not progress(db, job, worker_id, success):
                    return
                processed_ids.add(company.id)
            db.refresh(job, with_for_update=True)
            payload = dict(job.payload or {})
            new_ids = list(
                dict.fromkeys(
                    uuid.UUID(value)
                    for value in payload.get("form_first_company_ids", [])
                    if uuid.UUID(value) not in processed_ids and uuid.UUID(value) not in pending_ids
                )
            )
            payload.pop("form_first_company_ids", None)
            if new_ids:
                job.total_count += len(new_ids)
                pending_ids.extend(new_ids)
            job.payload = payload
            db.commit()
        return
    else:
        companies = next_form_analysis_batch(db, job.project_id, bool(job.payload.get("force")))
        queued_ids = list(
            dict.fromkeys(
                uuid.UUID(value) for value in job.payload.get("form_first_company_ids", [])
            )
        )
        analyzed_ids = {company.id for company in companies}
        queued_ids = [company_id for company_id in queued_ids if company_id not in analyzed_ids]
        job.total_count = len(companies) + len(queued_ids)
        db.commit()
        processed_ids = set()
        while companies or queued_ids:
            if not companies:
                batch_ids = queued_ids[:100]
                queued_ids = queued_ids[100:]
                companies = db.scalars(
                    select(Company)
                    .where(Company.project_id == job.project_id, Company.id.in_(batch_ids))
                    .order_by(Company.created_at, Company.id)
                ).all()
            for company in companies:
                if company.id in processed_ids:
                    continue
                if stop_requested(db, job, worker_id):
                    return
                profiles = analyze_company_forms(db, company, bool(job.payload.get("force")))
                success = bool(profiles) and any(
                    profile.form_status != "ERROR" for profile in profiles
                )
                if not progress(db, job, worker_id, success):
                    return
                processed_ids.add(company.id)
            companies = []
            db.refresh(job, with_for_update=True)
            payload = dict(job.payload or {})
            new_ids = list(
                dict.fromkeys(
                    uuid.UUID(value)
                    for value in payload.get("form_first_company_ids", [])
                    if uuid.UUID(value) not in processed_ids and uuid.UUID(value) not in queued_ids
                )
            )
            payload.pop("form_first_company_ids", None)
            queued_ids.extend(new_ids)
            job.total_count += len(new_ids)
            job.payload = payload
            db.commit()
            if queued_ids:
                continue
            if job.payload.get("force"):
                return
            companies = [
                company
                for company in next_form_analysis_batch(db, job.project_id)
                if company.id not in processed_ids
            ]
            if companies:
                job.total_count += len(companies)
                db.commit()


def run_form_dm_readiness(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    from app.form_dm_readiness_routes import (
        BLOCKING_REASONS,
        BROWSER_REVIEW_DIAGNOSTIC_REASONS,
        REVIEW_REASONS,
        _ranked_form_rows,
        classify_profile,
    )
    from app.models import FormAnalysisLog

    original_job = job
    job_id = job.id
    query = _ranked_form_rows(job.project_id)
    for attempt in range(READINESS_DATABASE_RETRY_LIMIT + 1):
        try:
            job.total_count = (
                db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
            )
            job.processed_count = job.success_count = job.failed_count = 0
            db.commit()
            break
        except DBAPIError as exc:
            db.rollback()
            transient = isinstance(exc, OperationalError) or exc.connection_invalidated
            if not transient or attempt >= READINESS_DATABASE_RETRY_LIMIT:
                raise
            logger.warning(
                "form readiness database retry phase=initialize attempt=%s",
                attempt + 1,
            )
            time.sleep(2**attempt)
            job = db.get(OperationJob, job_id)
            if job is None:
                return
    offset = 0
    while True:
        batch_complete = False
        for attempt in range(READINESS_DATABASE_RETRY_LIMIT + 1):
            try:
                job = db.get(OperationJob, job_id)
                if job is None or stop_requested(db, job, worker_id):
                    return
                persisted_count = (
                    db.scalar(
                        select(func.count())
                        .select_from(FormDmReadinessResult)
                        .where(FormDmReadinessResult.job_id == job_id)
                    )
                    or 0
                )
                offset = max(offset, persisted_count)
                rows = db.execute(query.offset(offset).limit(200)).all()
                if not rows:
                    job.processed_count = persisted_count
                    job.success_count = persisted_count
                    job.failed_count = 0
                    job.lease_expires_at = lease_deadline()
                    db.commit()
                    return
                classified_at = datetime.now(timezone.utc)
                profile_fingerprints = {
                    profile.id: profile.fingerprint for _, profile in rows if profile is not None
                }
                confirmed_review_pairs = {
                    (profile_id, fingerprint)
                    for profile_id, fingerprint, confirmed in db.execute(
                        select(
                            FormAnalysisLog.form_profile_id,
                            FormAnalysisLog.details["profile_fingerprint"].astext,
                            FormAnalysisLog.details["confirmed_no_sales_prohibition"].astext,
                        ).where(
                            FormAnalysisLog.form_profile_id.in_(profile_fingerprints),
                            FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
                        )
                    ).all()
                    if confirmed == "true"
                }
                results = []
                for company, profile in rows:
                    outcome = classify_profile(db, company, profile)
                    reasons = [outcome["primary_reason"], *outcome["secondary_reasons"]]
                    ready_confirmation_required = (
                        outcome["primary_reason"] == "READY"
                        and profile.is_primary is True
                        and (profile.id, profile.fingerprint) not in confirmed_review_pairs
                    )
                    queue_eligible = (
                        profile.is_primary is True
                        and len(profile.fingerprint or "") == 64
                        and (
                            bool(REVIEW_REASONS.intersection(reasons))
                            or ready_confirmation_required
                        )
                        and not bool(
                            (BLOCKING_REASONS - BROWSER_REVIEW_DIAGNOSTIC_REASONS).intersection(
                                reasons
                            )
                            if outcome["primary_reason"] == "BROWSER_READY"
                            else BLOCKING_REASONS.intersection(reasons)
                        )
                    )
                    results.append(
                        FormDmReadinessResult(
                            job_id=job_id,
                            company_id=company.id,
                            profile_id=profile.id,
                            primary_reason=outcome["primary_reason"],
                            secondary_reasons=outcome["secondary_reasons"],
                            review_queue_eligible=queue_eligible,
                            classified_at=classified_at,
                        )
                    )
                db.add_all(results)
                job.processed_count = offset + len(rows)
                job.success_count = offset + len(rows)
                job.lease_expires_at = lease_deadline()
                db.commit()
                offset += len(rows)
                db.expunge_all()
                db.add(original_job)
                db.refresh(original_job)
                job = original_job
                batch_complete = True
                break
            except DBAPIError as exc:
                db.rollback()
                transient = isinstance(exc, OperationalError) or exc.connection_invalidated
                if not transient or attempt >= READINESS_DATABASE_RETRY_LIMIT:
                    raise
                logger.warning(
                    "form readiness database retry phase=batch offset=%s attempt=%s",
                    offset,
                    attempt + 1,
                )
                time.sleep(2**attempt)
        if not batch_complete:
            return


def run_form_approval_batch(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    from fastapi import HTTPException

    from app.form_dm_readiness_routes import _preparation_reason, classify_profile
    from app.models import ApprovalRequest, FormAnalysisLog, FormProfile, OutreachDraft, User
    from app.services import human_approval
    from app.services.browser_form_preparation import preparation as browser_preparation
    from app.services.form_approval_preparation import preparation

    company_ids = [uuid.UUID(value) for value in job.payload.get("company_ids", [])]
    actor = db.get(User, uuid.UUID(job.payload["user_id"]))
    job.total_count = len(company_ids)
    db.commit()
    for company_id in company_ids:
        if stop_requested(db, job, worker_id):
            return
        outcome = {
            "company_id": str(company_id),
            "status": "blocked",
            "reason_code": "OTHER_UNSUPPORTED",
        }
        try:
            company = db.scalar(
                select(Company)
                .where(Company.id == company_id, Company.project_id == job.project_id)
                .with_for_update()
            )
            if company is None or actor is None:
                outcome["reason_code"] = "OTHER_UNSUPPORTED"
            else:
                profile = db.scalar(
                    select(FormProfile)
                    .where(FormProfile.company_id == company.id)
                    .order_by(
                        FormProfile.is_primary.desc(), FormProfile.updated_at.desc(), FormProfile.id
                    )
                    .limit(1)
                )
                readiness = (
                    classify_profile(db, company, profile)
                    if profile
                    else {"primary_reason": "OTHER_UNSUPPORTED"}
                )
                if readiness["primary_reason"] in {"READY", "BROWSER_READY"} and profile:
                    review_confirmed = db.scalar(
                        select(FormAnalysisLog.id)
                        .where(
                            FormAnalysisLog.form_profile_id == profile.id,
                            FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
                            FormAnalysisLog.details["profile_fingerprint"].astext
                            == profile.fingerprint,
                            FormAnalysisLog.details["confirmed_no_sales_prohibition"].astext
                            == "true",
                        )
                        .limit(1)
                    )
                    if not review_confirmed:
                        readiness = {"primary_reason": "FORM_REVIEW_REQUIRED"}
                if readiness["primary_reason"] not in {"READY", "BROWSER_READY"}:
                    readiness_reason = readiness["primary_reason"]
                    outcome["reason_code"] = (
                        "CAPTCHA"
                        if readiness_reason
                        in {"CAPTCHA_VISIBLE", "CAPTCHA_INVISIBLE", "CAPTCHA_LEGACY"}
                        else readiness_reason
                    )
                else:
                    draft = db.scalar(
                        select(OutreachDraft)
                        .where(
                            OutreachDraft.company_id == company.id, OutreachDraft.channel == "form"
                        )
                        .order_by(OutreachDraft.updated_at.desc(), OutreachDraft.id.desc())
                        .limit(1)
                    )
                    if draft is None:
                        outcome["reason_code"] = "NO_FORM_DRAFT"
                    else:
                        existing = db.scalar(
                            select(ApprovalRequest)
                            .where(
                                ApprovalRequest.project_id == job.project_id,
                                ApprovalRequest.company_id == company.id,
                                ApprovalRequest.source_draft_id == draft.id,
                                ApprovalRequest.channel == "form",
                            )
                            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
                            .limit(1)
                        )
                        if existing:
                            human_approval.invalidate_if_needed(db, existing)
                            db.flush()
                            if (
                                existing.status in {"PENDING", "APPROVED"}
                                and existing.expires_at > human_approval.now()
                            ):
                                outcome = {
                                    "company_id": str(company_id),
                                    "status": "skipped_existing",
                                    "reason_code": None,
                                }
                        if outcome["status"] != "skipped_existing":
                            browser_delivery = readiness["primary_reason"] == "BROWSER_READY"
                            proposal, _ = (
                                browser_preparation(db, company, draft)
                                if browser_delivery
                                else preparation(db, company, draft)
                            )
                            request = human_approval.create_proposal(
                                db,
                                job.project_id,
                                proposal,
                                "HUMAN",
                                actor.id,
                                allow_browser_preparation=browser_delivery,
                            )
                            outcome = {
                                "company_id": str(company_id),
                                "status": "created",
                                "reason_code": None,
                                "request_id": str(request.id),
                            }
        except HTTPException as exc:
            db.rollback()
            outcome["reason_code"] = _preparation_reason(str(exc.detail))
        except Exception:
            db.rollback()
            outcome["reason_code"] = "OTHER_UNSUPPORTED"
        if not progress(db, job, worker_id, outcome["status"] != "blocked"):
            return
        current_job = db.get(OperationJob, job.id)
        payload = dict(current_job.payload or {})
        payload["results"] = [*payload.get("results", []), outcome]
        current_job.payload = payload
        db.commit()


def run_article_extraction(db, job: OperationJob, worker_id: uuid.UUID) -> None:
    import hashlib

    from sqlalchemy import exists

    from app.model_article_extraction import CollectionArticleExtraction, CollectionExtractedEntry
    from app.model_collection_discovery import CollectionDiscoveryHit
    from app.model_collection_scheduler import CollectionSearchAttempt
    from app.services.article_extraction import EXTRACTOR_VERSION, extract_entries
    from app.services.collection import Candidate, canonicalize_url
    from app.services.collection_jobs import is_suppressed, save_candidates, start_job
    from app.services.scraper import SafeFetcher, ScrapeError, is_aggregator_domain

    operation_started = time.monotonic()
    article_limit = job.payload.get("article_limit", 20)
    operation_deadline = operation_started + article_limit * 70
    source_ids = {uuid.UUID(value) for value in job.payload["source_operation_ids"]}
    root_ids = set(
        db.scalars(
            select(CollectionSearchAttempt.root_operation_id).where(
                CollectionSearchAttempt.operation_job_id.in_(source_ids)
            )
        )
    )
    if root_ids:
        source_ids.update(
            db.scalars(
                select(CollectionSearchAttempt.operation_job_id).where(
                    CollectionSearchAttempt.root_operation_id.in_(root_ids)
                )
            )
        )
    hits = db.scalars(
        select(CollectionDiscoveryHit)
        .join(CollectionJob, CollectionJob.id == CollectionDiscoveryHit.collection_job_id)
        .where(
            CollectionJob.project_id == job.project_id,
            CollectionJob.operation_job_id.in_(source_ids),
            CollectionDiscoveryHit.classification == "ARTICLE",
            ~exists().where(
                CollectionArticleExtraction.discovery_hit_id == CollectionDiscoveryHit.id,
                CollectionArticleExtraction.extractor_version == EXTRACTOR_VERSION,
            ),
        )
        .order_by(CollectionDiscoveryHit.observed_at, CollectionDiscoveryHit.id)
        .limit(article_limit)
    ).all()
    job.total_count = len(hits)
    db.commit()
    for index, hit in enumerate(hits):
        if stop_requested(db, job, worker_id):
            return
        if time.monotonic() >= operation_deadline:
            job.error_message = "記事抽出操作の時間上限に達しました。"
            for _ in hits[index:]:
                if not progress(db, job, worker_id, False):
                    return
            return

        parent = db.get(CollectionJob, hit.collection_job_id)
        article_url = (hit.snapshot or {}).get("link", "")
        started = datetime.now(timezone.utc)
        extraction = CollectionArticleExtraction(
            project_id=job.project_id,
            operation_job_id=job.id,
            discovery_hit_id=hit.id,
            article_url=article_url,
            extractor_version=EXTRACTOR_VERSION,
            status="FETCHED",
            warnings=[],
        )
        db.add(extraction)
        db.flush()
        db.commit()
        usage_status = "failed"
        success = False
        fetcher = SafeFetcher()
        try:
            fetcher.site_root = article_url
            if not fetcher.robots_allowed(article_url):
                extraction.status = "ROBOTS_DISALLOWED"
            else:
                page = fetcher.fetch_html(article_url)
                extraction.final_url = page.url
                extraction.body_sha256 = hashlib.sha256(page.html.encode()).hexdigest()
                result = extract_entries(page.html, article_url)
                extraction.page_kind = result.page_kind
                extraction.pattern = result.entries[0].pattern if result.entries else ""
                extraction.warnings = list(result.warnings)
                extraction.status = (
                    "EXTRACTED" if result.page_kind == "LIST_ARTICLE" else result.page_kind
                )
                extraction.entry_count = len(result.entries)
                extraction.linked_count = sum(row.status == "LINKED" for row in result.entries)
                extraction.name_only_count = sum(
                    row.status == "NAME_ONLY" for row in result.entries
                )
                extraction.rejected_count = sum(row.status == "REJECTED" for row in result.entries)
                for row in result.entries:
                    entry = CollectionExtractedEntry(
                        extraction_id=extraction.id,
                        entry_order=row.order,
                        name=row.name,
                        name_key=row.name_key,
                        link_url=row.link_url,
                        link_kind=row.link_kind,
                        website_candidate=row.link_url if row.link_kind == "EXTERNAL_SITE" else "",
                        pattern=row.pattern,
                        locator=row.locator,
                        context=row.context,
                        status=row.status,
                        reasons=list(row.reasons),
                    )
                    db.add(entry)
                if not job.payload.get("dry_run"):
                    for entry in [row for row in result.entries if row.status == "LINKED"]:
                        if stop_requested(db, job, worker_id):
                            return
                        persisted = db.scalar(
                            select(CollectionExtractedEntry).where(
                                CollectionExtractedEntry.extraction_id == extraction.id,
                                CollectionExtractedEntry.entry_order == entry.order,
                            )
                        )
                        child = start_job(
                            db, job.project_id, "serper", parent.keyword, parent.region, job.id
                        )
                        candidate = Candidate(
                            company_name=entry.name,
                            website_url=entry.link_url,
                            reference_url=article_url,
                            search_excerpt=entry.context,
                            site_discovery={
                                "discovery_method": "ARTICLE_EXTRACT",
                                "article_url": article_url,
                                "article_title": (hit.snapshot or {}).get("title", ""),
                                "extraction_id": str(extraction.id),
                                "entry_id": str(persisted.id),
                            },
                        )
                        suppressed = is_suppressed(db, job.project_id, candidate)
                        _, entry_domain = canonicalize_url(entry.link_url)
                        save_candidates(db, child, [candidate])
                        persisted.collection_job_id = child.id
                        if child.saved_count:
                            persisted.disposition = "SAVED"
                            success = True
                            job.payload = {
                                **(job.payload or {}),
                                "article_saved_count": (job.payload or {}).get(
                                    "article_saved_count", 0
                                )
                                + child.saved_count,
                            }
                        elif child.duplicate_count:
                            persisted.disposition = "SUPPRESSED" if suppressed else "DUPLICATE"
                        elif child.excluded_count:
                            persisted.disposition = (
                                "AGGREGATOR_EXCLUDED"
                                if is_aggregator_domain(entry_domain)
                                else "NON_COMPANY_SOURCE"
                            )
                        else:
                            persisted.disposition = "INGESTION_CONFLICT"
                        persisted.company_id = db.scalar(
                            select(Company.id).where(
                                Company.project_id == job.project_id,
                                Company.company_name == entry.name,
                                Company.domain == entry_domain,
                            )
                        )
                        db.commit()
                usage_status = "completed"
                success = True
        except ScrapeError as exc:
            message = str(exc).lower()
            extraction.status = (
                "TOO_LARGE"
                if "サイズ" in message
                else (
                    "ROBOTS_DISALLOWED"
                    if "robots" in message
                    else (
                        "NOT_HTML"
                        if "html" in message or "コンテンツ" in message
                        else "FETCH_FAILED"
                    )
                )
            )
            extraction.warnings = [exc.public_message]
        finally:
            fetcher.close()
            elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
            db.add(
                LeadProcessingUsage(
                    project_id=job.project_id,
                    kind="search",
                    provider="article_fetch",
                    status=usage_status,
                    started_at=started,
                    elapsed_ms=elapsed,
                )
            )
            db.commit()
        if not progress(db, job, worker_id, success):
            return


def run_once() -> bool:
    if settings.worker_paused:
        return False
    with SessionLocal() as db:
        apply_application_settings(db)
        enqueue_due_schedules(db)
        enqueue_due_refresh_schedules(db)
        recover_stale_jobs(db)
        if settings.outbound_enabled:
            recover_stale_email_deliveries(db)
        if sync_inbound_mail(db):
            return True
        from app.services import approved_form, approved_form_worker

        form_dispatch = approved_form.claim(db)
        if form_dispatch is not None:
            form_dispatch_id = form_dispatch.id
            try:
                approved_form_worker.run(db, form_dispatch)
            except Exception as exc:
                db.rollback()
                logger.error(
                    "form dispatch persistence error: id=%s type=%s",
                    form_dispatch_id,
                    type(exc).__name__,
                )
            return True
        delivery = claim_email_delivery(db)
        if delivery is not None:
            run_email_delivery(db, delivery)
            return True
        job = claim_job(db)
        if job is None:
            return False
        worker_id = job.worker_id
        job_id = job.id
        logger.info("operation start: id=%s type=%s", job.id, job.operation_type)
        stamp_operation_runtime(job)
        db.commit()
        try:
            from app.services.bulk_template_drafts import run_bulk_template_drafts
            from app.services.form_consent_policy import run_consent_policy
            from app.services.form_label_rules import run_form_label_rule
            from app.services.master_data import backfill_project_sites
            from app.services.sales_preparation import run_preparation

            {
                "collect_search": run_collection,
                "web_analysis": run_web,
                "site_analysis": run_site_analysis,
                "ai_analysis": run_ai,
                "form_delivery": run_form_delivery,
                "form_intelligence": run_form_intelligence,
                "form_dm_readiness": run_form_dm_readiness,
                "prepare_outreach": lambda db, job, worker: run_preparation(
                    db, job, worker, stop_requested
                ),
                "extract_articles": run_article_extraction,
                "form_approval_batch": run_form_approval_batch,
                "bulk_template_drafts": lambda db, job, worker: run_bulk_template_drafts(
                    db, job, worker, stop_requested
                ),
                "master_site_backfill": lambda db, job, worker: backfill_project_sites(
                    db, job, worker, stop_requested
                ),
                "consent_policy": lambda db, job, worker: run_consent_policy(
                    db, job, worker, stop_requested, progress
                ),
                "form_label_rule": lambda db, job, worker: run_form_label_rule(
                    db, job, worker, stop_requested, progress
                ),
            }[job.operation_type](db, job, worker_id)
            job = db.get(OperationJob, job_id)
            db.refresh(job)
            stamp_operation_runtime(job)
            if job.status == "running" and job.worker_id == worker_id:
                job.status = (
                    "cancelled"
                    if job.cancel_requested
                    else ("completed" if job.failed_count == 0 else "failed")
                )
                job.error_message = (
                    ""
                    if job.status == "completed"
                    else (
                        "キャンセルされました。"
                        if job.status == "cancelled"
                        else "一部の処理に失敗しました。"
                    )
                )
                job.worker_id = None
                job.lease_expires_at = None
                job.finished_at = datetime.now(timezone.utc)
                if (
                    job.operation_type in {"site_analysis", "consent_policy", "form_label_rule"}
                    and job.processed_count
                ):
                    from app.services.site_analysis import enqueue_readiness_after_site_analysis

                    enqueue_readiness_after_site_analysis(db, job.project_id)
                elif job.operation_type == "collect_search" and (job.payload or {}).get(
                    "site_analysis_completed_during_collection"
                ):
                    from app.services.site_analysis import enqueue_readiness_after_site_analysis

                    enqueue_readiness_after_site_analysis(db, job.project_id)
                progress_state = (job.payload or {}).get("collection_progress") or {}
                chain = (job.payload or {}).get("collection_chain") or {}
                if (
                    job.status == "completed"
                    and job.operation_type == "collect_search"
                    and chain.get("auto_continue")
                    and progress_state.get("stop_reason") == "REQUEST_BUDGET_REACHED"
                    and progress_state.get("pending_queries", 0) > 0
                    and progress_state.get("total_requests", 0)
                    < chain.get("total_request_budget", 0)
                ):
                    from app.services.collection_continuation import enqueue_continuation

                    continuation = enqueue_continuation(db, job, automatic=True)
                    if continuation:
                        job.payload = {
                            **job.payload,
                            "collection_progress": {
                                **progress_state,
                                "stop_reason": "AUTO_CONTINUING",
                                "next_operation_id": str(continuation.id),
                            },
                        }
                db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(OperationJob, job.id)
            stamp_operation_runtime(job)
            if job.status == "running" and job.worker_id == worker_id:
                job.status = "failed"
                job.worker_id = None
                job.lease_expires_at = None
                from app.services.condition_collection import ConditionCollectionError

                job.error_message = (
                    str(exc)
                    if isinstance(exc, ConditionCollectionError)
                    else "バックグラウンド処理に失敗しました。"
                )
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
    if settings.worker_paused:
        raise SystemExit("Worker is paused for maintenance. Review recovery before resuming.")
    _heartbeat_once()
    stop_event = Event()
    heartbeat_thread = Thread(target=_heartbeat_loop, args=(stop_event,), daemon=True)
    heartbeat_thread.start()
    try:
        while True:
            worked = run_once()
            if args.once:
                return
            if not worked:
                time.sleep(max(0.5, min(args.poll_seconds, HEARTBEAT_INTERVAL_SECONDS)))
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=5)


if __name__ == "__main__":
    main()
