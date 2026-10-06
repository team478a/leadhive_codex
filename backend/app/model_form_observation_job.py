"""Append-only managed observation job diagnostics, never sending authority."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FormObservationJobEvent(Base):
    __tablename__ = "form_observation_job_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('QUEUED','CLAIMED','CANCEL_REQUESTED','CANCELLED',"
            "'COMPLETED','FAILED','RECOVERED')",
            name="ck_observation_job_event_type",
        ),
        CheckConstraint(
            "reason_code IN ('QUEUED','CLAIMED','CANCELLED','EVIDENCE_SAVED',"
            "'CLAIM_REJECTED','OBSERVATION_FAILED','BINDING_CHANGED','LEASE_CHANGED',"
            "'WORKER_LOST','PERMISSION_CHANGED','SOURCE_CHANGED','LAB_DISABLED')",
            name="ck_observation_job_reason",
        ),
        CheckConstraint(
            "(principal_type = 'HUMAN' AND actor_user_id IS NOT NULL) OR "
            "(principal_type = 'SYSTEM' AND actor_user_id IS NULL)",
            name="ck_observation_job_actor",
        ),
        CheckConstraint("attempt_number BETWEEN 0 AND 1000", name="ck_observation_job_attempt"),
        CheckConstraint(
            "before_status IS NULL OR before_status IN "
            "('queued','running','completed','failed','cancelled')",
            name="ck_observation_job_before",
        ),
        CheckConstraint(
            "after_status IN ('queued','running','completed','failed','cancelled')",
            name="ck_observation_job_after",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    operation_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("operation_jobs.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column()
    attempt_number: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    principal_type: Mapped[str] = mapped_column(String(10))
    event_type: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(30))
    before_status: Mapped[str | None] = mapped_column(String(12))
    after_status: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
