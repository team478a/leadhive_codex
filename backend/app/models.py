import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)


class TargetProfile(Timestamps, Base):
    __tablename__ = "target_profiles"
    __table_args__ = (
        CheckConstraint(
            "(is_system AND user_id IS NULL) OR (NOT is_system AND user_id IS NOT NULL)",
            name="ck_profile_owner",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    profile_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    search_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    positive_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    negative_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    exclusion_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    scoring_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    ai_instruction: Mapped[str] = mapped_column(Text, default="")
    default_regions: Mapped[list] = mapped_column(JSONB, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Timestamps, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_project_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    project_name: Mapped[str] = mapped_column(String(200))
    target_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_profiles.id"), index=True
    )
    sales_objective: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="draft")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Company(Timestamps, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("project_id", "domain", name="uq_company_project_domain"),
        UniqueConstraint("project_id", "website_url", name="uq_company_project_website"),
        Index(
            "uq_company_project_name_address",
            "project_id",
            "company_name",
            "address",
            unique=True,
            postgresql_where=text("address <> ''"),
        ),
        CheckConstraint(
            "source IN ('serper', 'google_places', 'url', 'csv')", name="ck_company_source"
        ),
        CheckConstraint(
            "analysis_status IN ('pending', 'running', 'completed', 'failed', 'skipped', "
            "'duplicate', 'excluded')",
            name="ck_company_analysis_status",
        ),
        CheckConstraint(
            "ai_status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="ck_company_ai_status",
        ),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_company_score"),
        CheckConstraint(
            "rank IS NULL OR rank IN ('A', 'B', 'C', '対象外')", name="ck_company_rank"
        ),
        CheckConstraint(
            "status IN ('unreviewed', 'target', 'approached', 'replied', 'meeting', "
            "'won', 'lost', 'excluded')",
            name="ck_company_sales_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    company_name: Mapped[str] = mapped_column(String(500))
    website_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(253))
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    source: Mapped[str] = mapped_column(String(30))
    source_keyword: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(30), default="unreviewed")
    notes: Mapped[str] = mapped_column(Text, default="")
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    assignee: Mapped[str] = mapped_column(String(200), default="", index=True)
    protected_fields: Mapped[list] = mapped_column(JSONB, default=list)
    prefecture: Mapped[str] = mapped_column(String(20), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    contact_url: Mapped[str] = mapped_column(Text, default="")
    instagram_url: Mapped[str] = mapped_column(Text, default="")
    x_url: Mapped[str] = mapped_column(Text, default="")
    tiktok_url: Mapped[str] = mapped_column(Text, default="")
    facebook_url: Mapped[str] = mapped_column(Text, default="")
    youtube_url: Mapped[str] = mapped_column(Text, default="")
    line_url: Mapped[str] = mapped_column(Text, default="")
    business_summary: Mapped[str] = mapped_column(Text, default="")
    website_text: Mapped[str] = mapped_column(Text, default="")
    analysis_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    analysis_error: Mapped[str] = mapped_column(String(500), default="")
    is_aggregator: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", name="fk_companies_duplicate_of_id", ondelete="SET NULL"),
        index=True,
    )
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None] = mapped_column(Integer, index=True)
    rank: Mapped[str | None] = mapped_column(String(20), index=True)
    is_target: Mapped[bool | None] = mapped_column(Boolean)
    business_type: Mapped[str] = mapped_column(String(300), default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    ai_strengths: Mapped[list] = mapped_column(JSONB, default=list)
    ai_concerns: Mapped[list] = mapped_column(JSONB, default=list)
    ai_recommended_approach: Mapped[str] = mapped_column(Text, default="")
    ai_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    ai_error: Mapped[str] = mapped_column(String(500), default="")
    ai_provider: Mapped[str] = mapped_column(String(50), default="")
    ai_model: Mapped[str] = mapped_column(String(100), default="")
    ai_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('note', 'call', 'email', 'form', 'sns', 'meeting', 'status_change')",
            name="ck_activity_type",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    activity_type: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionJob(Base):
    __tablename__ = "collection_jobs"
    __table_args__ = (
        CheckConstraint(
            "source IN ('serper', 'google_places', 'url', 'csv')", name="ck_job_source"
        ),
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_job_status"),
        CheckConstraint(
            "found_count >= 0 AND saved_count >= 0 AND duplicate_count >= 0 AND error_count >= 0",
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
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(String(500), default="")
    import_errors: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationJob(Base):
    __tablename__ = "operation_jobs"
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis')",
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
        CheckConstraint("source IN ('serper', 'google_places')", name="ck_search_schedule_source"),
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


class SavedCompanyFilter(Timestamps, Base):
    __tablename__ = "saved_company_filters"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    filters: Mapped[dict] = mapped_column(JSONB)
