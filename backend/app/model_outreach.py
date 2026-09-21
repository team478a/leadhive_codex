import secrets
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


class OutreachExperiment(Timestamps, Base):
    __tablename__ = "outreach_experiments"
    __table_args__ = (
        CheckConstraint("template_a_id <> template_b_id", name="ck_experiment_distinct_templates"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    template_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_templates.id", ondelete="RESTRICT"), index=True
    )
    template_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_templates.id", ondelete="RESTRICT"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OutreachDraft(Timestamps, Base):
    __tablename__ = "outreach_drafts"
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'form', 'sns')", name="ck_outreach_draft_channel"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    contact_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contact_people.id", ondelete="SET NULL"), index=True
    )
    channel: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    ai_provider: Mapped[str] = mapped_column(String(50), default="")
    ai_model: Mapped[str] = mapped_column(String(100), default="")
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outreach_experiments.id", ondelete="SET NULL"), index=True
    )
    experiment_variant: Mapped[str] = mapped_column(String(1), default="")


class OutreachTemplate(Timestamps, Base):
    __tablename__ = "outreach_templates"
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'form', 'sns')", name="ck_outreach_template_channel"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)


class OutreachDraftApproval(Base):
    __tablename__ = "outreach_draft_approvals"
    __table_args__ = (
        CheckConstraint(
            "approval_type IN ('email', 'form_direct', 'form_codex')",
            name="ck_outreach_draft_approval_type",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_drafts.id", ondelete="CASCADE"), index=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approval_type: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outreach_experiments.id", ondelete="SET NULL"), index=True
    )
    experiment_variant: Mapped[str] = mapped_column(String(1), default="")


class OutreachConversion(Base):
    __tablename__ = "outreach_conversions"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('replied', 'meeting', 'won')", name="ck_outreach_conversion_outcome"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_draft_approvals.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    inbound_email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inbound_emails.id", ondelete="SET NULL"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class EmailCampaign(Timestamps, Base):
    __tablename__ = "email_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'paused', 'completed')", name="ck_email_campaign_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_templates.id", ondelete="RESTRICT"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    followup_days: Mapped[int] = mapped_column(Integer, default=0)
    requested_count: Mapped[int] = mapped_column(Integer, default=0)


class EmailDelivery(Timestamps, Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'sent', 'failed', 'cancelled')",
            name="ck_email_delivery_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_email_delivery_attempt_count"),
        UniqueConstraint("draft_id", name="uq_email_delivery_draft"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_drafts.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(320))
    recipient_name: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[uuid.UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_message: Mapped[str] = mapped_column(String(500), default="")
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_campaigns.id", ondelete="SET NULL"), index=True
    )
    unsubscribe_token: Mapped[str] = mapped_column(
        String(64), default=lambda: secrets.token_urlsafe(32), unique=True, index=True
    )


class FormDelivery(Timestamps, Base):
    __tablename__ = "form_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'submitted', 'failed')", name="ck_form_delivery_status"
        ),
        CheckConstraint(
            "delivery_method IN ('direct', 'codex_assisted')", name="ck_form_delivery_method"
        ),
        UniqueConstraint("draft_id", name="uq_form_delivery_draft"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_drafts.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    form_url: Mapped[str] = mapped_column(Text)
    action_url: Mapped[str] = mapped_column(Text, default="")
    delivery_method: Mapped[str] = mapped_column(String(30), default="direct", index=True)
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)
    response_status: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str] = mapped_column(String(500), default="")
    result_note: Mapped[str] = mapped_column(String(500), default="")


class FormDeliveryBatch(Timestamps, Base):
    __tablename__ = "form_delivery_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'running', 'completed', 'cancelled')", name="ck_form_batch_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outreach_templates.id", ondelete="RESTRICT"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="ready", index=True)
    operation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operation_jobs.id", ondelete="SET NULL"), index=True
    )


class FormDeliveryBatchItem(Timestamps, Base):
    __tablename__ = "form_delivery_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "company_id", name="uq_form_batch_item_company"),
        CheckConstraint(
            "status IN ('queued', 'submitted', 'failed', 'manual_required', 'skipped')",
            name="ck_form_batch_item_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_delivery_batches.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outreach_drafts.id", ondelete="SET NULL"), index=True
    )
    form_delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_deliveries.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    reason: Mapped[str] = mapped_column(String(500), default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    codex_status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    codex_assignee: Mapped[str] = mapped_column(String(320), default="")
