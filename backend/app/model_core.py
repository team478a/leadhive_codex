import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class TargetProfile(Timestamps, Base):
    __tablename__ = "target_profiles"
    __table_args__ = (
        CheckConstraint(
            "(is_system AND user_id IS NULL) OR (NOT is_system AND user_id IS NOT NULL)",
            name="ck_profile_owner",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    profile_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    search_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    positive_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    negative_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    exclusion_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    scoring_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    ai_instruction: Mapped[str] = mapped_column(Text, default="")
    default_regions: Mapped[list] = mapped_column(JSONB, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Timestamps, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_project_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    project_name: Mapped[str] = mapped_column(String(200))
    target_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_profiles.id"), index=True
    )
    sales_objective: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="draft")


class ProjectMember(Timestamps, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        CheckConstraint("role IN ('editor', 'viewer')", name="ck_project_member_role"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
