"""Durable, bounded query cursors and billable search reservations."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollectionQueryTask(Base):
    __tablename__ = "collection_query_tasks"
    __table_args__ = (
        UniqueConstraint("root_operation_id", "query_order", name="uq_collection_query_order"),
        CheckConstraint(
            "next_page BETWEEN 1 AND 6 AND stagnant_pages BETWEEN 0 AND 2", name="ck_query_cursor"
        ),
        CheckConstraint("state IN ('READY','DONE','SOURCE_ERROR')", name="ck_query_state"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    root_operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_hash: Mapped[str] = mapped_column(String(64))
    query_order: Mapped[int] = mapped_column(Integer)
    keyword: Mapped[str] = mapped_column(String(500))
    region: Mapped[str] = mapped_column(String(500))
    next_page: Mapped[int] = mapped_column(Integer, default=1)
    stagnant_pages: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="READY")
    stop_reason: Mapped[str] = mapped_column(String(50), default="")
    last_attempt_order: Mapped[int] = mapped_column(Integer, default=0)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CollectionSearchAttempt(Base):
    __tablename__ = "collection_search_attempts"
    __table_args__ = (
        UniqueConstraint("root_operation_id", "attempt_order", name="uq_collection_attempt_order"),
        UniqueConstraint("collection_job_id", name="uq_collection_attempt_job"),
        CheckConstraint(
            "attempt_order BETWEEN 1 AND 50 AND page BETWEEN 1 AND 5",
            name="ck_search_attempt_bounds",
        ),
        CheckConstraint(
            "state IN ('RESERVED','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')",
            name="ck_search_attempt_state",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    root_operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_query_tasks.id", ondelete="CASCADE"), index=True
    )
    operation_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="CASCADE"), index=True
    )
    collection_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="CASCADE")
    )
    worker_id: Mapped[uuid.UUID] = mapped_column()
    attempt_order: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="RESERVED")
    reason: Mapped[str] = mapped_column(String(50), default="")
    raw_count: Mapped[int | None] = mapped_column(Integer)
    new_candidate_count: Mapped[int | None] = mapped_column(Integer)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
