"""One durable reservation and at most one attempt per Human approval."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApprovedFormDispatch(Base):
    __tablename__ = "approved_form_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','checking','submitted','failed','unknown','blocked','cancelled')",
            name="ck_approved_form_status",
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
