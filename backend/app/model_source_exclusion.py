"""Project-local, human-confirmed source domains; separate from contact suppression."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SourceDomainExclusion(Base):
    __tablename__ = "source_domain_exclusions"
    __table_args__ = (UniqueConstraint("project_id", "domain", name="uq_source_domain_project"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(253))
    reason: Mapped[str] = mapped_column(String(500))
    evidence_url: Mapped[str] = mapped_column(String(2048))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    history: Mapped[list] = mapped_column(JSONB, default=list)
