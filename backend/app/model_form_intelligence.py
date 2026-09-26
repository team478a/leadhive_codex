import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
from app.model_core import Timestamps

FORM_STATUSES = (
    "UNANALYZED",
    "READY",
    "REVIEW_REQUIRED",
    "BLOCKED",
    "STALE",
    "ERROR",
)
SALES_CONTACT_STATUSES = ("ALLOWED", "PROHIBITED", "UNCERTAIN")
CAPTCHA_TYPES = (
    "CAPTCHA_NONE",
    "CAPTCHA_RECAPTCHA",
    "CAPTCHA_HCAPTCHA",
    "CAPTCHA_TURNSTILE",
    "CAPTCHA_OTHER",
)
DECISION_SOURCES = ("DOM", "RULE", "JEV", "OPENAI", "MANUAL")


class FormProfile(Timestamps, Base):
    __tablename__ = "form_profiles"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "form_url", "form_index", name="uq_form_profile_company_url_index"
        ),
        CheckConstraint(
            "form_status IN ('UNANALYZED', 'READY', 'REVIEW_REQUIRED', 'BLOCKED', "
            "'STALE', 'ERROR')",
            name="ck_form_profile_status",
        ),
        CheckConstraint(
            "sales_contact_status IN ('ALLOWED', 'PROHIBITED', 'UNCERTAIN')",
            name="ck_form_profile_sales_contact_status",
        ),
        CheckConstraint(
            "captcha_type IN ('CAPTCHA_NONE', 'CAPTCHA_RECAPTCHA', 'CAPTCHA_HCAPTCHA', "
            "'CAPTCHA_TURNSTILE', 'CAPTCHA_OTHER')",
            name="ck_form_profile_captcha_type",
        ),
        CheckConstraint("form_index >= 0", name="ck_form_profile_form_index"),
        CheckConstraint("analysis_duration_ms >= 0", name="ck_form_profile_duration"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    form_url: Mapped[str] = mapped_column(Text)
    form_index: Mapped[int] = mapped_column(Integer, default=0)
    form_status: Mapped[str] = mapped_column(String(30), default="UNANALYZED", index=True)
    sales_contact_status: Mapped[str] = mapped_column(
        String(20), default="UNCERTAIN", index=True
    )
    captcha_type: Mapped[str] = mapped_column(String(30), default="CAPTCHA_NONE")
    confirmation_page: Mapped[bool | None] = mapped_column(Boolean)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    form_found: Mapped[bool] = mapped_column(Boolean, default=False)
    page_kind: Mapped[str] = mapped_column(String(50), default="general")
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    analysis_version: Mapped[str] = mapped_column(String(30), default="1.0")
    analysis_provider: Mapped[str] = mapped_column(String(50), default="rule")
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    analysis_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(String(500), default="")


class FormProfileField(Timestamps, Base):
    __tablename__ = "form_profile_fields"
    __table_args__ = (
        UniqueConstraint("form_profile_id", "position", name="uq_form_profile_field_position"),
        CheckConstraint("position >= 0", name="ck_form_profile_field_position"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_form_profile_field_confidence"
        ),
        CheckConstraint(
            "decision_source IN ('DOM', 'RULE', 'JEV', 'OPENAI', 'MANUAL')",
            name="ck_form_profile_field_decision_source",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_profiles.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    selector: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[str] = mapped_column(String(500), default="")
    name: Mapped[str] = mapped_column(String(500), default="")
    field_type: Mapped[str] = mapped_column(String(50))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    mapped_key: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    decision_source: Mapped[str] = mapped_column(String(20), default="RULE")
    recommended_value: Mapped[str] = mapped_column(String(500), default="")
    options: Mapped[list] = mapped_column(JSONB, default=list)
    placeholder: Mapped[str] = mapped_column(String(500), default="")
    aria_label: Mapped[str] = mapped_column(String(500), default="")
    surrounding_text: Mapped[str] = mapped_column(Text, default="")


class FormAnalysisLog(Base):
    __tablename__ = "form_analysis_logs"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('analysis_started', 'contact_page_found', 'form_found', "
            "'field_detected', 'field_mapped', 'ai_decision_requested', "
            "'ai_decision_completed', 'captcha_detected', 'sales_prohibition_detected', "
            "'analysis_completed', 'analysis_failed', 'manual_corrected')",
            name="ck_form_analysis_log_event_type",
        ),
        CheckConstraint("duration_ms >= 0", name="ck_form_analysis_log_duration"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_form_analysis_log_confidence",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    form_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_profiles.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    provider: Mapped[str] = mapped_column(String(50), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
