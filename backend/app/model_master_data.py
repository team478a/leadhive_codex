import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MasterCompany(Base):
    __tablename__ = "master_companies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed', 'non_company', 'unverified')",
            name="ck_master_company_status",
        ),
        Index(
            "uq_master_company_corporate_number",
            "corporate_number",
            unique=True,
            postgresql_where=text("corporate_number IS NOT NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    corporate_number: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(500), default="", server_default="")
    prefecture: Mapped[str] = mapped_column(String(20), default="", server_default="")
    city: Mapped[str] = mapped_column(String(200), default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(20), default="unverified", server_default="unverified"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MasterSite(Base):
    __tablename__ = "master_sites"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    host: Mapped[str] = mapped_column(String(253), unique=True)
    registrable_domain: Mapped[str] = mapped_column(String(253), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_site_name: Mapped[str] = mapped_column(String(500), default="", server_default="")


class MasterCompanySite(Base):
    __tablename__ = "master_company_sites"
    __table_args__ = (
        CheckConstraint(
            "relation IN ('primary', 'brand', 'store', 'unknown')",
            name="ck_master_company_site_relation",
        ),
        UniqueConstraint(
            "master_company_id",
            "master_site_id",
            "observed_at",
            name="uq_master_company_site_observed",
        ),
        Index("ix_master_company_site_active", "master_site_id", "valid_until"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    master_company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_companies.id", ondelete="CASCADE"), index=True
    )
    master_site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_sites.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MasterContactPage(Base):
    __tablename__ = "master_contact_pages"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    master_site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_sites.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(String(30), default="contact", server_default="contact")
    sales_prohibited: Mapped[bool | None] = mapped_column(Boolean)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MasterFormStructure(Base):
    __tablename__ = "master_form_structures"
    __table_args__ = (
        UniqueConstraint(
            "master_contact_page_id",
            "form_index",
            "fingerprint",
            name="uq_master_form_structure_fingerprint",
        ),
        CheckConstraint("form_index >= 0", name="ck_master_form_structure_index"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    master_contact_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("master_contact_pages.id", ondelete="CASCADE"), index=True
    )
    form_index: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    fields: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    captcha_type: Mapped[str] = mapped_column(String(30), default="CAPTCHA_NONE")
    submission_kind: Mapped[str] = mapped_column(String(50), default="")
    confirmation_page: Mapped[bool | None] = mapped_column(Boolean)
    analysis_version: Mapped[str] = mapped_column(String(30))
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MasterFormReview(Base):
    __tablename__ = "master_form_reviews"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "contact_page_hash",
            "form_index",
            "fingerprint",
            name="uq_master_form_review_org_page_form",
        ),
        CheckConstraint("form_index >= 0", name="ck_master_form_review_form_index"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    contact_page_url: Mapped[str] = mapped_column(Text)
    contact_page_hash: Mapped[str] = mapped_column(String(64))
    form_index: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    fields_hash: Mapped[str] = mapped_column(String(64))
    mapping_snapshot: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    confirmed_no_sales_prohibition: Mapped[bool] = mapped_column(Boolean)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MasterObservation(Base):
    __tablename__ = "master_observations"
    __table_args__ = (
        CheckConstraint(
            "(master_company_id IS NOT NULL)::int + (master_site_id IS NOT NULL)::int = 1",
            name="ck_master_observation_subject",
        ),
        CheckConstraint(
            "source IN ('site', 'nta', 'gbizinfo', 'form_first', 'google_places')",
            name="ck_master_observation_source",
        ),
        CheckConstraint(
            "source <> 'google_places' OR field = 'place_id'",
            name="ck_master_observation_google_place_id_only",
        ),
        Index(
            "ix_master_observation_company_field_time",
            "master_company_id",
            "field",
            "observed_at",
        ),
        Index("ix_master_observation_site_field_time", "master_site_id", "field", "observed_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    master_company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("master_companies.id", ondelete="CASCADE")
    )
    master_site_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("master_sites.id", ondelete="CASCADE")
    )
    field: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    observed_by_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
