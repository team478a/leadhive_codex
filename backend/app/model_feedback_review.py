"""Project-scoped research proposals; never delivery or runtime rule authority."""

import uuid
from datetime import datetime

from sqlalchemy import (
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


class FeedbackProposal(Base):
    __tablename__ = "feedback_proposals"
    __table_args__ = (UniqueConstraint("project_id", "input_hash", "proposal_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    proposal_key: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackProposalDecision(Base):
    __tablename__ = "feedback_proposal_decisions"
    __table_args__ = (
        UniqueConstraint("proposal_id", "version"),
        CheckConstraint(
            "state IN ('ACCEPTED', 'REJECTED', 'DEFERRED')", name="ck_feedback_decision_state"
        ),
        CheckConstraint("version > 0", name="ck_feedback_decision_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_proposals.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    restored_from: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackEvaluation(Base):
    """Immutable aggregate checkpoint and optional fixed comparison."""

    __tablename__ = "feedback_evaluations"
    __table_args__ = (UniqueConstraint("project_id", "record_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    record_key: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSONB)
    comparison: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    previous_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("feedback_evaluations.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackEvaluationNote(Base):
    """Authenticated operator explanation, not a new Human Truth label."""

    __tablename__ = "feedback_evaluation_notes"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "version"),
        CheckConstraint("version > 0", name="ck_feedback_evaluation_note_version"),
        CheckConstraint(
            "reason IN ('INSUFFICIENT_EVALUATION', 'COHORT_CHANGED', 'NO_MEASURED_GAIN', "
            "'REGRESSION', 'NOT_APPLIED', 'OTHER')",
            name="ck_feedback_evaluation_note_reason",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_evaluations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
