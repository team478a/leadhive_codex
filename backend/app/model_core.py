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
    event,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

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
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            name="fk_projects_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    organization = relationship("Organization")
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


@event.listens_for(Session, "before_flush")
def assign_project_organization(session: Session, _flush_context, _instances) -> None:
    from app.model_operations import SuppressionEntry
    from app.model_organizations import Organization, OrganizationMember

    pending_by_owner: dict[uuid.UUID, Organization] = {}
    pending_projects: dict[uuid.UUID, Project] = {}
    pending_organizations: dict[uuid.UUID, Organization] = {}
    for project in session.new:
        if not isinstance(project, Project):
            continue
        pending_projects[project.id] = project
        if project.organization_id is not None:
            continue
        organization = pending_by_owner.get(project.user_id)
        if organization is None:
            membership = session.scalar(
                select(OrganizationMember)
                .join(Organization, Organization.id == OrganizationMember.organization_id)
                .where(
                    OrganizationMember.user_id == project.user_id,
                    OrganizationMember.role.in_(("owner", "admin")),
                    Organization.status == "active",
                )
                .order_by(Organization.created_at, Organization.id)
                .limit(1)
            )
            if membership is not None:
                project.organization_id = membership.organization_id
                continue
            owner = session.get(User, project.user_id)
            organization = Organization(
                id=uuid.uuid4(),
                name=f"利用企業 - {(owner.email if owner else str(project.user_id))[:180]}",
                status="active",
            )
            session.add(organization)
            session.add(
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=project.user_id,
                    role="owner",
                )
            )
            pending_by_owner[project.user_id] = organization
            pending_organizations[organization.id] = organization
            project.organization = organization
        project.organization_id = organization.id
    for entry in session.new:
        if not isinstance(entry, SuppressionEntry) or entry.project_id is None:
            continue
        if entry.scope not in {None, "organization"} or entry.organization_id is not None:
            continue
        project = pending_projects.get(entry.project_id) or session.get(Project, entry.project_id)
        if project is None or project.organization_id is None:
            continue
        entry.scope = "organization"
        entry.project_id = None
        entry.organization_id = project.organization_id
        organization = pending_organizations.get(project.organization_id)
        if organization is None:
            organization = getattr(project, "organization", None)
        if organization is not None:
            entry.organization = organization
