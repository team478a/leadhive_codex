import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.model_core import Timestamps


class SuppressionEntry(Timestamps, Base):
    __tablename__ = "suppression_entries"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(253), default="", index=True)
    email: Mapped[str] = mapped_column(String(320), default="", index=True)
    phone: Mapped[str] = mapped_column(String(100), default="", index=True)
    reason: Mapped[str] = mapped_column(String(500))


class CollectionJob(Base):
    __tablename__ = "collection_jobs"
    __table_args__ = (
        CheckConstraint(
            "source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv')", name="ck_job_source"
        ),
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_job_status"),
        CheckConstraint(
            "found_count >= 0 AND saved_count >= 0 AND duplicate_count >= 0 AND "
            "excluded_count >= 0 AND error_count >= 0 AND processing_ms >= 0",
            name="ck_job_counts",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    operation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="SET NULL"), index=True
    )
    search_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("search_schedules.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(30))
    keyword: Mapped[str] = mapped_column(String(500), default="")
    region: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    processing_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(String(500), default="")
    import_errors: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationJob(Base):
    __tablename__ = "operation_jobs"
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery')",
            name="ck_operation_job_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_operation_job_status",
        ),
        CheckConstraint(
            "total_count >= 0 AND processed_count >= 0 AND success_count >= 0 "
            "AND failed_count >= 0",
            name="ck_operation_job_counts",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_operation_job_attempt_count"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    operation_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[uuid.UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchSchedule(Timestamps, Base):
    __tablename__ = "search_schedules"
    __table_args__ = (
        CheckConstraint(
            "source IN ('serper', 'google_places', 'gbizinfo')", name="ck_search_schedule_source"
        ),
        CheckConstraint("max_results BETWEEN 1 AND 100", name="ck_search_schedule_max_results"),
        CheckConstraint("interval_hours BETWEEN 1 AND 720", name="ck_search_schedule_interval"),
        CheckConstraint("company_limit BETWEEN 1 AND 100000", name="ck_search_schedule_limit"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(30))
    keywords: Mapped[list] = mapped_column(JSONB)
    region: Mapped[str] = mapped_column(String(500))
    max_results: Mapped[int] = mapped_column(Integer, default=20)
    interval_hours: Mapped[int] = mapped_column(Integer, default=168)
    company_limit: Mapped[int] = mapped_column(Integer, default=10000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(String(500), default="")


class AnalysisRefreshSchedule(Timestamps, Base):
    __tablename__ = "analysis_refresh_schedules"
    __table_args__ = (
        CheckConstraint(
            "interval_hours BETWEEN 1 AND 720", name="ck_analysis_refresh_schedule_interval"
        ),
        CheckConstraint(
            "stale_days BETWEEN 1 AND 3650", name="ck_analysis_refresh_schedule_stale_days"
        ),
        CheckConstraint(
            "batch_limit BETWEEN 1 AND 100", name="ck_analysis_refresh_schedule_batch_limit"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )
    interval_hours: Mapped[int] = mapped_column(Integer, default=168)
    stale_days: Mapped[int] = mapped_column(Integer, default=90)
    batch_limit: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(String(500), default="")


class SavedCompanyFilter(Timestamps, Base):
    __tablename__ = "saved_company_filters"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    filters: Mapped[dict] = mapped_column(JSONB)
