import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FormDmReadinessResult(Base):
    __tablename__ = "form_dm_readiness_results"
    __table_args__ = (
        UniqueConstraint("job_id", "company_id", name="uq_form_dm_readiness_job_company"),
        Index("ix_form_dm_readiness_job_reason", "job_id", "primary_reason"),
        Index(
            "ix_form_dm_readiness_review_queue",
            "job_id",
            "review_queue_eligible",
            "company_id",
        ),
        Index("ix_form_dm_readiness_job_company", "job_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_profiles.id", ondelete="CASCADE"), nullable=False
    )
    primary_reason: Mapped[str] = mapped_column(String(40), nullable=False)
    secondary_reasons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    review_queue_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
