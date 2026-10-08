"""Additive lead evidence and destination inventory; never grants sending authority."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LeadSourceObservation(Base):
    __tablename__ = "lead_source_observations"
    __table_args__ = (
        UniqueConstraint(
            "collection_job_id", "company_id", "observation_hash", name="uq_lead_source_observation"
        ),
        CheckConstraint(
            "identity_status IN ('CONFIRMED','PROBABLE','REVIEW_REQUIRED','DIFFERENT')",
            name="ck_lead_identity_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    collection_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_jobs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str] = mapped_column(Text, default="")
    terms_reference: Mapped[str] = mapped_column(Text, default="")
    allowed_usage: Mapped[str] = mapped_column(String(40), default="REVIEW_REQUIRED")
    attribution_requirement: Mapped[str] = mapped_column(Text, default="")
    observation_hash: Mapped[str] = mapped_column(String(64))
    identity_status: Mapped[str] = mapped_column(String(20))
    identity_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    applied_fields: Mapped[list] = mapped_column(JSONB, default=list)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LeadSiteEvidence(Base):
    __tablename__ = "lead_site_evidence"
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('CONFIRMED','HIGH','MEDIUM','LOW','REVIEW_REQUIRED')",
            name="ck_lead_site_confidence",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    identity_hash: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ContactDestination(Base):
    __tablename__ = "contact_destinations"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "destination_type",
            "shared_destination_key",
            name="uq_contact_destination_project_key",
        ),
        CheckConstraint("destination_type IN ('email','form')", name="ck_contact_destination_type"),
        CheckConstraint(
            "scope IN ('company','location','group','unknown')", name="ck_contact_destination_scope"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    destination_type: Mapped[str] = mapped_column(String(10))
    destination: Mapped[str] = mapped_column(Text)
    shared_destination_key: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(20), default="unknown")
    purpose: Mapped[str] = mapped_column(String(30), default="unknown")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeadDestinationLink(Base):
    __tablename__ = "lead_destination_links"
    __table_args__ = (
        UniqueConstraint("company_id", "destination_id", name="uq_lead_destination_link"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_destinations.id", ondelete="CASCADE"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[int] = mapped_column(Integer, default=0)
