"""One durable reservation and at most one attempt per Human approval."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FormDispatchLimits(Base):
    __tablename__ = "form_dispatch_limits"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_form_limits_singleton"),
        CheckConstraint("site_interval_seconds BETWEEN 60 AND 86400", name="ck_form_site_interval"),
        CheckConstraint(
            "daily_limit BETWEEN 1 AND 1000 AND hourly_limit BETWEEN 1 AND 100 "
            "AND minimum_interval_seconds BETWEEN 60 AND 86400",
            name="ck_form_limits_range",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    daily_limit: Mapped[int] = mapped_column(Integer, default=30)
    hourly_limit: Mapped[int] = mapped_column(Integer, default=5)
    minimum_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    site_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovedFormDispatch(Base):
    __tablename__ = "approved_form_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','checking','submitted','failed','unknown','blocked','cancelled')",
            name="ck_approved_form_status",
        ),
        CheckConstraint(
            "payload_snapshot->>'delivery_method' <> 'form_adapter' OR "
            "(status IN ('queued','blocked','cancelled') AND started_at IS NULL "
            "AND delivery_id IS NULL AND worker_id IS NULL)",
            name="ck_adapter_reservation_not_started",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_requests.id"), unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outreach_drafts.id"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    payload_snapshot: Mapped[dict] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    form_url: Mapped[str] = mapped_column(Text, index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    worker_id: Mapped[uuid.UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("form_deliveries.id"))
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FormDispatchSite(Base):
    __tablename__ = "form_dispatch_sites"
    dispatch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approved_form_dispatches.id"), primary_key=True
    )
    site_key: Mapped[str] = mapped_column(String(253), primary_key=True, index=True)
