import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
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
