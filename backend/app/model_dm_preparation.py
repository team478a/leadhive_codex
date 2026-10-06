"""Evidence-bound template preparation; never sending authority."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LeadDmPreparation(Base):
    __tablename__ = "lead_dm_preparations"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + interval '7 days'",
            name="ck_dm_preparation_expiry",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column()
    choice_id: Mapped[uuid.UUID] = mapped_column()
    choice_version: Mapped[int] = mapped_column()
    template_id: Mapped[uuid.UUID] = mapped_column()
    template_hash: Mapped[str] = mapped_column(String(64))
    context_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
