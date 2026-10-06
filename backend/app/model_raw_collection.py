"""Isolated raw discovery observations and Human truth, never delivery authority."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RawBenchmark(Base):
    __tablename__ = "raw_benchmarks"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), unique=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    region: Mapped[str] = mapped_column(String(500))
    industry: Mapped[str] = mapped_column(String(300))
    definition_version: Mapped[str] = mapped_column(String(40), default="raw-pilot-v1")
    code_commit: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RawQueryRun(Base):
    __tablename__ = "raw_query_runs"
    __table_args__ = (
        UniqueConstraint("benchmark_id", "ordinal", name="uq_raw_run_order"),
        UniqueConstraint(
            "benchmark_id", "source", "keyword", "repeat_index", name="uq_raw_run_repeat"
        ),
        CheckConstraint("repeat_index BETWEEN 1 AND 3", name="ck_raw_run_repeat"),
        CheckConstraint("requested_count BETWEEN 1 AND 30", name="ck_raw_run_count"),
        CheckConstraint(
            "status IN ('RUNNING','COMPLETED','FAILED','CANCELLED')", name="ck_raw_run_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    benchmark_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_benchmarks.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    repeat_index: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    source: Mapped[str] = mapped_column(String(30))
    keyword: Mapped[str] = mapped_column(String(300))
    query: Mapped[str] = mapped_column(String(1000))
    requested_count: Mapped[int] = mapped_column(Integer)
    code_commit: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawLeadSnapshot(Base):
    __tablename__ = "raw_lead_snapshots"
    __table_args__ = (UniqueConstraint("run_id", "position", name="uq_raw_snapshot_position"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_query_runs.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RawReviewSession(Base):
    __tablename__ = "raw_review_sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_lead_snapshots.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawLeadReview(Base):
    __tablename__ = "raw_lead_reviews"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "version", name="uq_raw_review_version"),
        UniqueConstraint("session_id", name="uq_raw_review_session"),
        CheckConstraint("version > 0", name="ck_raw_review_version"),
        CheckConstraint("duration_seconds BETWEEN 0 AND 14400", name="ck_raw_review_duration"),
        CheckConstraint(
            "outcome IN ('CORRECT','WRONG_INDUSTRY','WRONG_AREA','DUPLICATE',"
            "'WRONG_ENTITY','PORTAL_OR_AGGREGATOR','CLOSED_OR_INACTIVE','UNCERTAIN','OTHER')",
            name="ck_raw_review_outcome",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_lead_snapshots.id"), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_review_sessions.id"))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str] = mapped_column(Text)
    entity_key: Mapped[str] = mapped_column(String(100), default="")
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_lead_snapshots.id"))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RawPairReview(Base):
    __tablename__ = "raw_pair_reviews"
    __table_args__ = (
        UniqueConstraint("left_id", "right_id", "version", name="uq_raw_pair_version"),
        UniqueConstraint("session_id", name="uq_raw_pair_session"),
        CheckConstraint("left_id < right_id", name="ck_raw_pair_order"),
        CheckConstraint("outcome IN ('SAME','DIFFERENT','UNSURE')", name="ck_raw_pair_outcome"),
        CheckConstraint("version > 0", name="ck_raw_pair_version"),
        CheckConstraint("duration_seconds BETWEEN 0 AND 14400", name="ck_raw_pair_duration"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    left_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_lead_snapshots.id"), index=True)
    right_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_lead_snapshots.id"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_review_sessions.id"))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer)
    pair_hash: Mapped[str] = mapped_column(String(64))
    features: Mapped[dict] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
