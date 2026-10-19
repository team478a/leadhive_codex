from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Activity,
    CF7Observation,
    CollectionConditionRequest,
    CollectionFactReview,
    CollectionJob,
    Company,
    ExternalPresenceSearch,
    FeatureUsageEvent,
    FormDeliveryBatch,
    LeadCompletionCohort,
    LeadProcessingUsage,
    LeadReviewSession,
    OperationJob,
    RawBenchmark,
    RawLeadReview,
    RawLeadSnapshot,
    RawPairReview,
    RawQueryRun,
    RawReviewSession,
    User,
)
from app.security import current_admin

router = APIRouter(prefix="/api/admin", tags=["admin-usage"])


def _grouped_counts(db: Session, model, dimensions: tuple, time_column, since: datetime):
    statement = (
        select(*dimensions, func.count().label("count"))
        .select_from(model)
        .where(time_column >= since)
        .group_by(*dimensions)
        .order_by(*dimensions)
    )
    keys = [column.key for column in dimensions]
    return [dict(zip(keys, row[:-1]), count=row[-1]) for row in db.execute(statement)]


def _count_since(db: Session, model, time_column, since: datetime) -> int:
    return db.scalar(
        select(func.count()).select_from(model).where(time_column >= since)
    ) or 0


@router.get("/usage-report")
def usage_report(
    db: Session = Depends(get_db),
    _user: User = Depends(current_admin),
):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=90)

    processing_usage = db.execute(
        select(
            LeadProcessingUsage.kind,
            LeadProcessingUsage.provider,
            LeadProcessingUsage.model,
            LeadProcessingUsage.status,
            LeadProcessingUsage.currency,
            func.count().label("event_count"),
            func.sum(LeadProcessingUsage.estimated_cost).label("estimated_cost"),
            func.count(case((LeadProcessingUsage.estimated_cost.is_(None), 1))).label(
                "cost_missing_count"
            ),
            func.sum(LeadProcessingUsage.input_tokens).label("input_tokens"),
            func.sum(LeadProcessingUsage.output_tokens).label("output_tokens"),
            func.count(case((LeadProcessingUsage.input_tokens.is_(None), 1))).label(
                "input_tokens_missing_count"
            ),
            func.count(case((LeadProcessingUsage.output_tokens.is_(None), 1))).label(
                "output_tokens_missing_count"
            ),
        )
        .where(LeadProcessingUsage.started_at >= since)
        .group_by(
            LeadProcessingUsage.kind,
            LeadProcessingUsage.provider,
            LeadProcessingUsage.model,
            LeadProcessingUsage.status,
            LeadProcessingUsage.currency,
        )
        .order_by(
            LeadProcessingUsage.kind,
            LeadProcessingUsage.provider,
            LeadProcessingUsage.model,
            LeadProcessingUsage.status,
            LeadProcessingUsage.currency,
        )
    )
    processing_rows = [
        {
            "kind": row.kind,
            "provider": row.provider,
            "model": row.model,
            "status": row.status,
            "currency": row.currency,
            "event_count": row.event_count,
            "estimated_cost": str(row.estimated_cost) if row.estimated_cost is not None else None,
            "cost_missing_count": row.cost_missing_count,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "input_tokens_missing_count": row.input_tokens_missing_count,
            "output_tokens_missing_count": row.output_tokens_missing_count,
        }
        for row in processing_usage
    ]

    input_activity = db.execute(
        select(
            func.count(case((Activity.note.like("PC入力試行接続 v1: %"), Activity.id))).label(
                "pc_trials"
            ),
            func.count(case((Activity.note.like("保存HTML入力報告 v1: %"), Activity.id))).label(
                "pc_reports"
            ),
            func.count(case((Activity.note.like("実ページ入力専用依頼 v1: %"), Activity.id))).label(
                "live_trials"
            ),
            func.count(case((Activity.note.like("実ページ入力報告 v1: %"), Activity.id))).label(
                "live_reports"
            ),
        ).where(Activity.created_at >= since)
    ).one()

    cf7_counts = db.execute(
        select(
            func.count().label("total"),
            func.count(case((CF7Observation.expires_at > now, 1))).label("active"),
            func.count(case((CF7Observation.expires_at <= now, 1))).label("expired"),
        ).where(CF7Observation.observed_at >= since)
    ).one()

    batch_current = db.execute(
        select(
            func.count(case((FormDeliveryBatch.status.in_(("ready", "running")), 1))).label(
                "active_count"
            ),
            func.max(FormDeliveryBatch.created_at).label("latest_created_at"),
        )
    ).one()

    operation_active = db.execute(
        select(OperationJob.operation_type, OperationJob.status, func.count().label("count"))
        .where(OperationJob.status.in_(("queued", "running")))
        .group_by(OperationJob.operation_type, OperationJob.status)
        .order_by(OperationJob.operation_type, OperationJob.status)
    )

    collection_active = db.execute(
        select(CollectionJob.source, func.count().label("count"))
        .where(CollectionJob.status == "running")
        .group_by(CollectionJob.source)
        .order_by(CollectionJob.source)
    )

    return {
        "window_days": 90,
        "window_start": since,
        "generated_at": now,
        "coverage": {
            "processing_usage_partial": True,
            "historical_proposal_events_available": False,
            "note": (
                "API/AI利用量は計測済み記録のみです。条件提案・PC/live入力イベントは"
                "記録導入後のみ集計し、過去の未記録分は復元できません。"
            ),
        },
        "collection_jobs": _grouped_counts(
            db,
            CollectionJob,
            (CollectionJob.source, CollectionJob.status),
            CollectionJob.created_at,
            since,
        ),
        "active_collection_jobs": [
            {"source": row.source, "count": row.count} for row in collection_active
        ],
        "companies_by_source": _grouped_counts(
            db, Company, (Company.source,), Company.created_at, since
        ),
        "operation_jobs": _grouped_counts(
            db,
            OperationJob,
            (OperationJob.operation_type, OperationJob.status),
            OperationJob.created_at,
            since,
        ),
        "active_operation_jobs": [
            {"operation_type": row.operation_type, "status": row.status, "count": row.count}
            for row in operation_active
        ],
        "form_delivery_batches": _grouped_counts(
            db, FormDeliveryBatch, (FormDeliveryBatch.status,), FormDeliveryBatch.created_at, since
        ),
        "active_form_delivery_batches": batch_current.active_count,
        "latest_form_delivery_batch_at": batch_current.latest_created_at,
        "processing_usage": processing_rows,
        "external_presence_searches": _grouped_counts(
            db,
            ExternalPresenceSearch,
            (ExternalPresenceSearch.platform, ExternalPresenceSearch.status),
            ExternalPresenceSearch.created_at,
            since,
        ),
        "collection_condition_requests": _count_since(
            db, CollectionConditionRequest, CollectionConditionRequest.confirmed_at, since
        ),
        "collection_fact_reviews": _count_since(
            db, CollectionFactReview, CollectionFactReview.created_at, since
        ),
        "feature_usage_events": _grouped_counts(
            db,
            FeatureUsageEvent,
            (FeatureUsageEvent.event_type, FeatureUsageEvent.outcome),
            FeatureUsageEvent.created_at,
            since,
        ),
        "historical_proposal_calls": None,
        "raw": {
            "benchmarks": _count_since(db, RawBenchmark, RawBenchmark.created_at, since),
            "query_runs": _count_since(db, RawQueryRun, RawQueryRun.created_at, since),
            "snapshots": _count_since(db, RawLeadSnapshot, RawLeadSnapshot.collected_at, since),
            "review_sessions": _count_since(
                db, RawReviewSession, RawReviewSession.started_at, since
            ),
            "lead_reviews": _count_since(db, RawLeadReview, RawLeadReview.reviewed_at, since),
            "pair_reviews": _count_since(db, RawPairReview, RawPairReview.reviewed_at, since),
        },
        "completion_metrics": {
            "cohorts": _count_since(
                db, LeadCompletionCohort, LeadCompletionCohort.created_at, since
            ),
            "review_sessions": _count_since(
                db, LeadReviewSession, LeadReviewSession.started_at, since
            ),
        },
        "legacy_input_activity_counts": {
            "pc_trials": input_activity.pc_trials,
            "pc_reports": input_activity.pc_reports,
            "live_trials": input_activity.live_trials,
            "live_reports": input_activity.live_reports,
            "coverage": "activity prefix counts; legacy data only",
        },
        "cf7_fixture_observations": {
            "total": cf7_counts.total,
            "active": cf7_counts.active,
            "expired": cf7_counts.expired,
            "coverage": "controlled fixtures only, not production usage",
        },
    }
