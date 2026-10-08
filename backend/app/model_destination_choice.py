"""Human preparation choice evidence; never sending authority."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DestinationChoiceEvent(Base):
    __tablename__ = "destination_choice_events"
    __table_args__ = (
        UniqueConstraint("company_id", "version", name="uq_destination_choice_version"),
        CheckConstraint(
            "version > 0 AND purpose_review_version > 0", name="ck_destination_choice_version"
        ),
        CheckConstraint("event_type IN ('SELECTED','REVOKED')", name="ck_destination_choice_event"),
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + interval '7 days'",
            name="ck_destination_choice_expiry",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Historical IDs are retained through merge/delete, never reassigned to another Lead.
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    destination_id: Mapped[uuid.UUID] = mapped_column()
    actor_user_id: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(20))
    destination_type: Mapped[str] = mapped_column(String(10))
    destination: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    purpose_review_version: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
