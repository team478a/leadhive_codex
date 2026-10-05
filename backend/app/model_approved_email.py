"""Durable reservations and execution evidence for human-approved email."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BulkApprovalProof(Base):
    __tablename__ = "bulk_approval_proofs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    session_hash: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    items: Mapped[list] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovedEmailBatch(Base):
    __tablename__ = "approved_email_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','paused','completed','cancelled')", name="ck_approved_batch_status"
        ),
        CheckConstraint(
            "daily_limit BETWEEN 1 AND 10000 AND hourly_limit BETWEEN 1 AND 1000",
            name="ck_approved_batch_limits",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    daily_limit: Mapped[int] = mapped_column(Integer, default=500)
    hourly_limit: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovedEmailReservation(Base):
    __tablename__ = "approved_email_reservations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approved_email_batches.id"), index=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_requests.id"), unique=True)
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("email_deliveries.id"), unique=True)
    envelope: Mapped[dict] = mapped_column(JSONB)
    envelope_hash: Mapped[str] = mapped_column(String(64))
    sender_email: Mapped[str] = mapped_column(String(320), index=True)
    recipient_email: Mapped[str] = mapped_column(String(320), index=True)


class EmailSendAttempt(Base):
    __tablename__ = "email_send_attempts"
    __table_args__ = (
        CheckConstraint(
            "result IN ('STARTED','SMTP_ACCEPTED','FAILED','UNKNOWN')",
            name="ck_email_attempt_result",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approved_email_reservations.id"), unique=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_version: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[str] = mapped_column(String(400), unique=True)
    result: Mapped[str] = mapped_column(String(20), default="STARTED")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
