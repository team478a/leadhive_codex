"""Credential separation. An Agent credential is never converted into a User."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.model_approval import AgentCredential, AgentIdentity, AgentProjectGrant, OutreachAuditEvent
from app.schema_approval import AGENT_SCOPES


def denial(db: Session, event: str, reason: str, actor_id=None, project_id=None, item=None):
    db.add(
        OutreachAuditEvent(
            event=event,
            principal_type="AGENT" if actor_id else "SYSTEM",
            actor_id=actor_id,
            project_id=project_id,
            request_id=item.id if item else None,
            company_id=item.company_id if item else None,
            payload_hash=item.payload_hash if item else None,
            payload_version=item.payload_version if item else None,
            before_status=item.status if item else None,
            after_status=item.status if item else None,
            reason=reason,
        )
    )
    db.commit()


def reject_agent_on_human_route(request: Request, db: Session):
    if request.headers.get("authorization"):
        from app.model_approval import ApprovalRequest
        from app.security import token_digest

        parts = request.headers["authorization"].split()
        credential = (
            db.scalar(
                select(AgentCredential).where(AgentCredential.token_hash == token_digest(parts[1]))
            )
            if len(parts) == 2
            else None
        )
        item = None
        value = request.path_params.get("request_id")
        try:
            item = db.get(ApprovalRequest, UUID(str(value))) if value else None
        except ValueError:
            pass
        denial(
            db,
            "authentication denied",
            "agent credential on human route",
            credential.agent_id if credential else None,
            item.project_id if item else None,
            item,
        )
        raise HTTPException(403, "Agent認証はHuman操作に使用できません。")


def reject_mixed_credentials(request: Request, db: Session = Depends(get_db)):
    from app.security import COOKIE_NAME

    if request.headers.get("authorization") and request.cookies.get(COOKIE_NAME):
        denial(db, "authentication denied", "mixed human and agent credentials")
        raise HTTPException(403, "認証方式を混在できません。")


@dataclass(frozen=True)
class AgentPrincipal:
    id: UUID
    credential_id: UUID


def authenticate_agent(request: Request, db: Session, project_id: UUID, scope: str):
    from app.security import COOKIE_NAME, token_digest

    header = request.headers.get("authorization", "")
    if request.cookies.get(COOKIE_NAME):
        denial(db, "authentication denied", "human cookie on agent route")
        raise HTTPException(403, "認証方式を混在できません。")
    if not settings.agent_features_enabled:
        denial(db, "authentication denied", "agent feature disabled")
        raise HTTPException(403, "Agent機能は無効です。")
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 200:
        denial(db, "authentication denied", "invalid agent credential")
        raise HTTPException(401, "Agent認証が必要です。")
    credential = db.scalar(
        select(AgentCredential)
        .where(AgentCredential.token_hash == token_digest(parts[1]))
        .with_for_update()
    )
    identity = db.get(AgentIdentity, credential.agent_id) if credential else None
    if (
        not credential
        or credential.revoked
        or not identity
        or not identity.active
        or credential.expires_at <= datetime.now(timezone.utc)
    ):
        denial(db, "authentication denied", "invalid agent credential")
        raise HTTPException(401, "Agent認証が無効です。")
    grant = db.scalar(
        select(AgentProjectGrant)
        .where(
            AgentProjectGrant.agent_id == identity.id, AgentProjectGrant.project_id == project_id
        )
        .with_for_update()
    )
    if (
        not grant
        or not grant.active
        or scope not in AGENT_SCOPES
        or not set(credential.scopes) <= AGENT_SCOPES
        or not set(grant.scopes) <= AGENT_SCOPES
        or scope not in credential.scopes
        or scope not in grant.scopes
    ):
        denial(db, "scope denied", "scope or project denied", identity.id)
        raise HTTPException(403, "Agent権限がありません。")
    return AgentPrincipal(identity.id, credential.id)
