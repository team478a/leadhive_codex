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
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.model_core import Timestamps


class ApplicationSettings(Timestamps, Base):
    """Administrator-managed service settings. Secrets are stored encrypted."""

    __tablename__ = "application_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_app_url: Mapped[str] = mapped_column(String(2000), default="")
    openai_model: Mapped[str] = mapped_column(String(200), default="")
    openai_api_key_ciphertext: Mapped[str] = mapped_column(Text, default="")
    serper_api_key_ciphertext: Mapped[str] = mapped_column(Text, default="")
    google_places_api_key_ciphertext: Mapped[str] = mapped_column(Text, default="")
    gbizinfo_api_token_ciphertext: Mapped[str] = mapped_column(Text, default="")
    gbizinfo_api_base_url: Mapped[str] = mapped_column(String(2000), default="")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class SmtpSettings(Timestamps, Base):
    __tablename__ = "smtp_settings"
    __table_args__ = (
        CheckConstraint(
            "max_emails_per_day BETWEEN 1 AND 10000", name="ck_smtp_settings_daily_limit"
        ),
        CheckConstraint(
            "minimum_interval_seconds BETWEEN 0 AND 3600", name="ck_smtp_settings_interval"
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(320), default="")
    password_ciphertext: Mapped[str] = mapped_column(Text, default="")
    from_email: Mapped[str] = mapped_column(String(320))
    from_name: Mapped[str] = mapped_column(String(200), default="LeadHive")
    use_starttls: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[float] = mapped_column()
    max_emails_per_day: Mapped[int] = mapped_column(Integer, default=100)
    minimum_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class InboundMailSettings(Timestamps, Base):
    __tablename__ = "inbound_mail_settings"
    __table_args__ = (
        CheckConstraint(
            "poll_interval_seconds BETWEEN 60 AND 86400",
            name="ck_inbound_mail_settings_poll_interval",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(320))
    password_ciphertext: Mapped[str] = mapped_column(Text, default="")
    mailbox: Mapped[str] = mapped_column(String(200), default="INBOX")
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[float] = mapped_column()
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(String(500), default="")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class InboundEmail(Timestamps, Base):
    __tablename__ = "inbound_emails"
    __table_args__ = (
        UniqueConstraint("mailbox_uid", name="uq_inbound_email_mailbox_uid"),
        CheckConstraint(
            "match_type IN ('company_email', 'contact_person', 'manual', 'unmatched')",
            name="ck_inbound_email_match_type",
        ),
        CheckConstraint(
            "classification IN ('reply', 'bounce', 'unsubscribe', 'other')",
            name="ck_inbound_email_classification",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    mailbox_uid: Mapped[str] = mapped_column(String(100))
    message_id: Mapped[str] = mapped_column(String(500), default="")
    sender_email: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    preview: Mapped[str] = mapped_column(String(1000), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    outreach_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outreach_draft_approvals.id", ondelete="SET NULL"), index=True
    )
    handled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    match_type: Mapped[str] = mapped_column(String(30), default="unmatched")
    classification: Mapped[str] = mapped_column(String(20), default="reply")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "notification_type IN "
            "('followup_overdue', 'operation_failed', 'email_delivery_failed', "
            "'inbound_reply_received', 'followup_due_today')",
            name="ck_notification_type",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    operation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="CASCADE"), index=True
    )
    email_delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_deliveries.id", ondelete="CASCADE"), index=True
    )
    inbound_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inbound_emails.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(String(1000))
    dedupe_key: Mapped[str] = mapped_column(String(500), unique=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
