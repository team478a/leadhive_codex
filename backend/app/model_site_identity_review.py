"""Version-bound Human identity evidence, independent of sending approval."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteIdentityReviewEvent(Base):
    __tablename__ = "site_identity_review_events"
    __table_args__ = (
        UniqueConstraint("company_id", "version", name="uq_site_identity_review_version"),
        CheckConstraint("version > 0", name="ck_site_identity_review_version"),
        CheckConstraint(
            "event_type IN ('CONFIRMED','REVOKED')", name="ck_site_identity_review_event"
        ),
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + interval '7 days'",
            name="ck_site_identity_review_expiry",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Keep original identities through Company merge/delete; never transfer attestation.
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(20))
    identity_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    observed_name: Mapped[str] = mapped_column(String(300))
    observed_address: Mapped[str] = mapped_column(String(1000))
    observed_phone: Mapped[str] = mapped_column(String(100))
    evidence_excerpt: Mapped[str] = mapped_column(String(1000))
    reasons: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
