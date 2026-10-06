"""Diagnostic evidence only; never a form profile or dispatch authorization."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FormObservationEvidence(Base):
    __tablename__ = "form_observation_evidence"
    __table_args__ = (
        UniqueConstraint(
            "operation_job_id", "run_id", "attempt_number", name="uq_observation_attempt"
        ),
        CheckConstraint("attempt_number BETWEEN 1 AND 1000", name="ck_observation_attempt"),
        CheckConstraint("snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_observation_hash"),
        CheckConstraint("octet_length(canonical_snapshot) <= 32768", name="ck_observation_size"),
        CheckConstraint(
            "expires_at > observed_at AND expires_at <= observed_at + interval '24 hours'",
            name="ck_observation_expiry",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    operation_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operation_jobs.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column()
    attempt_number: Mapped[int] = mapped_column(Integer)
    lease_worker_id: Mapped[uuid.UUID] = mapped_column()
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    canonical_snapshot: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64))


class FormObservationEvent(Base):
    __tablename__ = "form_observation_events"
    __table_args__ = (
        Index(
            "uq_observation_saved_event",
            "evidence_id",
            unique=True,
            postgresql_where=text("event_type = 'SAVED'"),
        ),
        CheckConstraint("event_type IN ('SAVED','RETIRED')", name="ck_observation_event_type"),
        CheckConstraint(
            "principal_type IN ('HUMAN','SYSTEM')", name="ck_observation_event_principal"
        ),
        CheckConstraint(
            "reason_code IN ('EVIDENCE_SAVED','HUMAN_RETIRED')", name="ck_observation_event_reason"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    operation_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operation_jobs.id"), index=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_observation_evidence.id"), index=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    principal_type: Mapped[str] = mapped_column(String(10))
    event_type: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(30))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
