import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FormLabelRule(Base):
    __tablename__ = "form_label_rules"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'RETIRED')", name="ck_form_label_rule_status"),
        Index(
            "uq_form_label_rules_active_project_label_type",
            "project_id",
            "normalized_label",
            "field_type",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    normalized_label: Mapped[str] = mapped_column(Text)
    field_type: Mapped[str] = mapped_column(String(50))
    mapped_key: Mapped[str] = mapped_column(String(50))
    recommended_value: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", server_default="ACTIVE")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FormLabelAiSuggestion(Base):
    __tablename__ = "form_label_ai_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'ACCEPTED', 'DISMISSED', 'UNAVAILABLE')",
            name="ck_form_label_ai_suggestion_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_form_label_ai_suggestion_confidence",
        ),
        CheckConstraint(
            "sample_count >= 1",
            name="ck_form_label_ai_suggestion_sample_count",
        ),
        Index(
            "uq_form_label_ai_suggestions_open_project_label_type",
            "project_id",
            "normalized_label",
            "field_type",
            unique=True,
            postgresql_where=text("status IN ('ACTIVE', 'UNAVAILABLE')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    normalized_label: Mapped[str] = mapped_column(Text)
    field_type: Mapped[str] = mapped_column(String(50))
    suggested_mapped_key: Mapped[str] = mapped_column(
        String(50), default="unknown", server_default="unknown"
    )
    confidence: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    sample_count: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(50), default="", server_default="")
    model: Mapped[str] = mapped_column(String(100), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", server_default="ACTIVE")
    reason: Mapped[str] = mapped_column(String(500), default="", server_default="")
    usage: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    accepted_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_label_rules.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
