import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FeatureUsageEvent(Base):
    __tablename__ = "feature_usage_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('collection_condition_proposal', 'pc_input_trial_issued', "
            "'pc_input_report_recorded', 'live_input_trial_issued', 'live_input_report_recorded')",
            name="ck_feature_usage_event_type",
        ),
        CheckConstraint("outcome IN ('completed', 'failed')", name="ck_feature_usage_outcome"),
        Index("ix_feature_usage_events_created_type", "created_at", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(
        String(20), default="completed", server_default="completed"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
