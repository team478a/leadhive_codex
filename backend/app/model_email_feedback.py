"""Delivery evidence is separate from SMTP transport state."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmailFeedbackEvent(Base):
    __tablename__ = "email_feedback_events"
    __table_args__ = (
        UniqueConstraint("source", "event_key", name="uq_email_feedback_source_key"),
        CheckConstraint(
            "kind IN ('delivered','hard_bounce','soft_bounce','complaint','unsubscribe')",
            name="ck_email_feedback_kind",
        ),
        CheckConstraint("source IN ('HUMAN','PROVIDER')", name="ck_email_feedback_source"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("email_deliveries.id"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    event_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    recipient: Mapped[str] = mapped_column(String(320))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class EmailHealthState(Base):
    __tablename__ = "email_health_states"
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(300), default="")
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    review_failures: Mapped[int] = mapped_column(Integer, default=0)
    review_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
