"""Durable, non-sending sales preparation checkpoints."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SalesPreparationItem(Base):
    __tablename__ = "sales_preparation_items"
    __table_args__ = (
        UniqueConstraint("job_id", "company_id", name="uq_preparation_job_company"),
        CheckConstraint(
            "status IN ('pending','running','ready','review','blocked','error')",
            name="ck_preparation_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outreach_drafts.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    stage: Mapped[str] = mapped_column(String(30), default="pending")
    reason: Mapped[str] = mapped_column(String(500), default="")
    channel: Mapped[str] = mapped_column(String(20), default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
