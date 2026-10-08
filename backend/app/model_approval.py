"""A2 preparation/approval records. No dispatch authority or send attempts."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentIdentity(Base):
    __tablename__ = "agent_identities"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentCredential(Base):
    __tablename__ = "agent_credentials"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_identities.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentProjectGrant(Base):
    __tablename__ = "agent_project_grants"
    __table_args__ = (UniqueConstraint("agent_id", "project_id", name="uq_agent_project_grant"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_identities.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    scopes: Mapped[list] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXPIRED','REVOKED','CONSUMED')",
            name="ck_approval_status",
        ),
        CheckConstraint("channel IN ('email','form')", name="ck_approval_channel"),
        CheckConstraint(
            "created_by_principal_type IN ('HUMAN','AGENT')", name="ck_approval_creator"
        ),
        CheckConstraint("payload_version > 0", name="ck_approval_version"),
        CheckConstraint(
            "delivery_method <> 'cf7_candidate_only' OR status <> 'CONSUMED'",
            name="ck_cf7_candidate_not_consumed",
        ),
        CheckConstraint(
            "delivery_method <> 'cf7_real_candidate_only' OR status <> 'CONSUMED'",
            name="ck_cf7_real_candidate_not_consumed",
        ),
        CheckConstraint(
            "delivery_method <> 'form_plan_fixture' OR status <> 'CONSUMED'",
            name="ck_fixture_plan_not_consumed",
        ),
        CheckConstraint(
            "delivery_method <> 'form_adapter' OR status <> 'CONSUMED' OR "
            "current_database() ~ '_test$'",
            name="ck_adapter_contract_not_consumed",
        ),
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + interval '24 hours'",
            name="ck_approval_expiry",
        ),
        UniqueConstraint("proposal_id", "payload_version", name="uq_approval_proposal_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    delivery_method: Mapped[str] = mapped_column(String(30))
    source_draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outreach_drafts.id"))
    recipient: Mapped[str | None] = mapped_column(String(320))
    form_url: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    sender: Mapped[dict] = mapped_column(JSONB)
    field_values: Mapped[dict] = mapped_column(JSONB)
    payload_snapshot: Mapped[dict] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_version: Mapped[int] = mapped_column(Integer)
    canonicalization_version: Mapped[str] = mapped_column(String(30), default="json-v1")
    proposal_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    supersedes_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_requests.id"), unique=True
    )
    created_by_principal_type: Mapped[str] = mapped_column(String(10))
    created_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_identities.id"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_payload_hash: Mapped[str | None] = mapped_column(String(64))
    approved_payload_version: Mapped[int | None] = mapped_column(Integer)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    invalidation_reason: Mapped[str | None] = mapped_column(Text)


class HumanApprovalProof(Base):
    __tablename__ = "human_approval_proofs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_requests.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    session_hash: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20), default="APPROVE")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    method: Mapped[str] = mapped_column(String(30), default="password-v1")


class OutreachAuditEvent(Base):
    __tablename__ = "outreach_audit_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event: Mapped[str] = mapped_column(String(60))
    principal_type: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_requests.id"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    payload_version: Mapped[int | None] = mapped_column(Integer)
    before_status: Mapped[str | None] = mapped_column(String(20))
    after_status: Mapped[str | None] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str | None] = mapped_column(String(200))
