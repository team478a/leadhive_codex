"""Human purpose evidence, separate from contact permission and send approval."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DestinationReviewEvent(Base):
    __tablename__ = "destination_review_events"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "destination_id", "version", name="uq_destination_review_version"
        ),
        CheckConstraint("version > 0", name="ck_destination_review_version"),
        CheckConstraint(
            "event_type IN ('CONFIRMED','REVOKED')", name="ck_destination_review_event"
        ),
        CheckConstraint(
            "purpose IN ('general','business','partnership','sales','support',"
            "'recruitment','reservation','unknown')",
            name="ck_destination_review_purpose",
        ),
        CheckConstraint(
            "scope IN ('company','location','group','unknown')", name="ck_destination_review_scope"
        ),
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + interval '7 days'",
            name="ck_destination_review_expiry",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Historical IDs intentionally survive Company merge/delete and inventory refresh.
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    destination_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(30))
    scope: Mapped[str] = mapped_column(String(20))
    source_url: Mapped[str] = mapped_column(Text)
    evidence_excerpt: Mapped[str] = mapped_column(String(1000))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    canonicalization_version: Mapped[str] = mapped_column(
        String(30), default="destination-review-v1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
