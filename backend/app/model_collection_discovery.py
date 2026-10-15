"""Normal collection observations, independent of benchmark/Human truth."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollectionDiscoveryHit(Base):
    __tablename__ = "collection_discovery_hits"
    __table_args__ = (
        UniqueConstraint("collection_job_id", "position", name="uq_discovery_hit_position"),
        CheckConstraint("position BETWEEN 1 AND 100", name="ck_discovery_hit_position"),
        CheckConstraint(
            "disposition IN ('CAPTURED','SAVED','DUPLICATE','SUPPRESSED',"
            "'AGGREGATOR_EXCLUDED','TARGET_LIMIT','RESPONSE_LIMIT','INVALID_URL',"
            "'NON_COMPANY_SOURCE','INGESTION_CONFLICT')",
            name="ck_discovery_hit_disposition",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    collection_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column()
    snapshot: Mapped[dict] = mapped_column(JSONB)
    raw_hash: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(30))
    classification_version: Mapped[str] = mapped_column(String(20), default="1")
    classification_reason: Mapped[str] = mapped_column(String(100))
    disposition: Mapped[str] = mapped_column(String(30), default="CAPTURED")
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
