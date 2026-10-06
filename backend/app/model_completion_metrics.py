"""Measurement records only. Neither a review nor a cohort authorizes delivery."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LeadCompletionCohort(Base):
    __tablename__ = "lead_completion_cohorts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    company_ids: Mapped[list] = mapped_column(JSONB)
    cohort_hash: Mapped[str] = mapped_column(String(64))
    context_hash: Mapped[str] = mapped_column(String(64))
    definition_version: Mapped[str] = mapped_column(String(30), default="completion-a2-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeadReviewSession(Base):
    __tablename__ = "lead_review_sessions"
    __table_args__ = (
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('CHECKED','REVIEW','HOLD','BLOCKED','STALE','ABANDONED')",
            name="ck_lead_review_outcome",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="ck_lead_review_time"
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 0 AND 14400",
            name="ck_lead_review_duration",
        ),
        Index(
            "uq_lead_review_active",
            "cohort_id",
            "user_id",
            unique=True,
            postgresql_where=text("finished_at IS NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lead_completion_cohorts.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = (
        mapped_column()
    )  # Retain denominator/review even after lead deletion.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    identity_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(20))


class LeadProcessingUsage(Base):
    __tablename__ = "lead_processing_usage"
    __table_args__ = (
        CheckConstraint("kind IN ('search','ai')", name="ck_lead_usage_kind"),
        CheckConstraint("status IN ('completed','failed')", name="ck_lead_usage_status"),
        CheckConstraint("elapsed_ms >= 0", name="ck_lead_usage_elapsed"),
        CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="ck_lead_usage_cost"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_lead_usage_input"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_lead_usage_output"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    collection_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    currency: Mapped[str | None] = mapped_column(String(3))
    pricing_version: Mapped[str | None] = mapped_column(String(100))
