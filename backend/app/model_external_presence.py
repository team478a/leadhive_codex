"""Presence inventory and provenance; never a contact permission store."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExternalPresence(Base):
    __tablename__ = "external_presences"
    __table_args__ = (
        UniqueConstraint("company_id", "platform", name="uq_presence_company_platform"),
        CheckConstraint(
            "status IN ('FOUND','NOT_FOUND','NOT_CHECKED','ERROR')", name="ck_presence_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    discovery_method: Mapped[str] = mapped_column(String(30), default="PASSIVE")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(100), default="")
    identity_hash: Mapped[str] = mapped_column(String(64), default="")


class ExternalPresenceEvidence(Base):
    __tablename__ = "external_presence_evidence"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    collection_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="SET NULL"), index=True
    )
    platform: Mapped[str] = mapped_column(String(40))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    discovery_method: Mapped[str] = mapped_column(String(30))
    association: Mapped[str] = mapped_column(String(30))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExternalPresenceSearch(Base):
    """Committed before network I/O; uncertain/aborted attempts are not automatically replayed."""

    __tablename__ = "external_presence_searches"
    __table_args__ = (
        UniqueConstraint("collection_job_id", "company_id", "platform", name="uq_presence_search"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    collection_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="CASCADE"), index=True
    )
    operation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="SET NULL"), index=True
    )
    budget_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="STARTED")
    reason: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
