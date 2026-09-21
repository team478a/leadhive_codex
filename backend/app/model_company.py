import uuid
from datetime import date, datetime

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
from app.model_core import Timestamps


class Company(Timestamps, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("project_id", "domain", name="uq_company_project_domain"),
        UniqueConstraint("project_id", "website_url", name="uq_company_project_website"),
        Index(
            "uq_company_project_name_address",
            "project_id",
            "company_name",
            "address",
            unique=True,
            postgresql_where=text("address <> ''"),
        ),
        CheckConstraint(
            "source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv')",
            name="ck_company_source",
        ),
        CheckConstraint(
            "analysis_status IN ('pending', 'running', 'completed', 'failed', 'skipped', "
            "'duplicate', 'excluded')",
            name="ck_company_analysis_status",
        ),
        CheckConstraint(
            "ai_status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="ck_company_ai_status",
        ),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_company_score"),
        CheckConstraint(
            "rank IS NULL OR rank IN ('A', 'B', 'C', '対象外')", name="ck_company_rank"
        ),
        CheckConstraint(
            "status IN ('unreviewed', 'target', 'approached', 'replied', 'meeting', "
            "'won', 'lost', 'excluded')",
            name="ck_company_sales_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    company_name: Mapped[str] = mapped_column(String(500))
    website_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(253))
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    source: Mapped[str] = mapped_column(String(30))
    source_keyword: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(30), default="unreviewed")
    notes: Mapped[str] = mapped_column(Text, default="")
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    assignee: Mapped[str] = mapped_column(String(200), default="", index=True)
    protected_fields: Mapped[list] = mapped_column(JSONB, default=list)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exclusion_reason: Mapped[str] = mapped_column(String(500), default="")
    contact_quality_status: Mapped[str] = mapped_column(String(20), default="unknown")
    contact_source_url: Mapped[str] = mapped_column(Text, default="")
    contact_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prefecture: Mapped[str] = mapped_column(String(20), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    contact_url: Mapped[str] = mapped_column(Text, default="")
    instagram_url: Mapped[str] = mapped_column(Text, default="")
    x_url: Mapped[str] = mapped_column(Text, default="")
    tiktok_url: Mapped[str] = mapped_column(Text, default="")
    facebook_url: Mapped[str] = mapped_column(Text, default="")
    youtube_url: Mapped[str] = mapped_column(Text, default="")
    line_url: Mapped[str] = mapped_column(Text, default="")
    business_summary: Mapped[str] = mapped_column(Text, default="")
    website_text: Mapped[str] = mapped_column(Text, default="")
    scraped_urls: Mapped[list] = mapped_column(JSONB, default=list)
    analysis_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    analysis_error: Mapped[str] = mapped_column(String(500), default="")
    is_aggregator: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", name="fk_companies_duplicate_of_id", ondelete="SET NULL"),
        index=True,
    )
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None] = mapped_column(Integer, index=True)
    rank: Mapped[str | None] = mapped_column(String(20), index=True)
    is_target: Mapped[bool | None] = mapped_column(Boolean)
    business_type: Mapped[str] = mapped_column(String(300), default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    ai_strengths: Mapped[list] = mapped_column(JSONB, default=list)
    ai_concerns: Mapped[list] = mapped_column(JSONB, default=list)
    ai_recommended_approach: Mapped[str] = mapped_column(Text, default="")
    ai_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    ai_error: Mapped[str] = mapped_column(String(500), default="")
    ai_provider: Mapped[str] = mapped_column(String(50), default="")
    ai_model: Mapped[str] = mapped_column(String(100), default="")
    ai_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('note', 'call', 'email', 'form', 'sns', 'meeting', 'status_change')",
            name="ck_activity_type",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    activity_type: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactPerson(Timestamps, Base):
    __tablename__ = "contact_people"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('unknown', 'verified', 'invalid')",
            name="ck_contact_person_verification_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    verification_status: Mapped[str] = mapped_column(String(20), default="unknown")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")


class AiReview(Timestamps, Base):
    __tablename__ = "ai_reviews"
    __table_args__ = (
        CheckConstraint("verdict IN ('correct', 'incorrect')", name="ck_ai_review_verdict"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), unique=True, index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    verdict: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")


class Deal(Timestamps, Base):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('lead', 'proposal', 'negotiation', 'won', 'lost')", name="ck_deal_stage"
        ),
        CheckConstraint("expected_amount >= 0", name="ck_deal_expected_amount"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    stage: Mapped[str] = mapped_column(String(20), default="lead", index=True)
    expected_amount: Mapped[int] = mapped_column(Integer, default=0)
    expected_close_date: Mapped[date | None] = mapped_column()
    owner: Mapped[str] = mapped_column(String(200), default="")
    next_step: Mapped[str] = mapped_column(Text, default="")
    lost_reason: Mapped[str] = mapped_column(String(500), default="")
