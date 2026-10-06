"""Append-only controlled evidence, not executable form profiles."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CF7Observation(Base):
    __tablename__ = "cf7_observations"
    __table_args__ = (
        CheckConstraint("source_kind = 'CONTROLLED_FIXTURE'", name="ck_cf7_observation_source"),
        CheckConstraint(
            "expires_at > observed_at AND expires_at <= observed_at + interval '24 hours'",
            name="ck_cf7_observation_expiry",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    form_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("form_profiles.id"), index=True)
    source_kind: Mapped[str] = mapped_column(String(30), default="CONTROLLED_FIXTURE")
    observer_version: Mapped[str] = mapped_column(String(30))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_snapshot: Mapped[dict] = mapped_column(JSONB)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
