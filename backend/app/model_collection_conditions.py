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


class CollectionConditionRequest(Base):
    """Immutable confirmed revisions. No update/delete API or send authorization."""

    __tablename__ = "collection_condition_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_condition_request_project_version"),
        CheckConstraint("version > 0", name="ck_condition_request_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    collection_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CollectionFactReview(Base):
    """Human predicate evidence; append-only API, never a sending approval."""

    __tablename__ = "collection_fact_reviews"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "condition_type", "value", "version", name="uq_fact_review_version"
        ),
        CheckConstraint("condition_type IN ('AREA','INDUSTRY')", name="ck_fact_review_type"),
        CheckConstraint("outcome IN ('MATCH','NO_MATCH','UNKNOWN')", name="ck_fact_review_outcome"),
        CheckConstraint("version > 0", name="ck_fact_review_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    condition_type: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    company_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text, default="")
    evidence_excerpt: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
