"""Human-owned source memory, with read access for project viewers."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SourceDomainExclusion, User
from app.project_access import project_access
from app.security import current_user
from app.services.collection_feedback import correction_url
from app.services.source_exclusions import domain_key

router = APIRouter(prefix="/api/projects/{project_id}/source-exclusions")


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    evidence_url: str = Field(min_length=1, max_length=2048)
    reason: str = Field(min_length=1, max_length=500)
    confirmed_domain_wide: Literal[True]


@router.get("")
def list_sources(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    return db.scalars(
        select(SourceDomainExclusion)
        .where(SourceDomainExclusion.project_id == project_id)
        .order_by(SourceDomainExclusion.created_at.desc())
    ).all()


@router.post("", status_code=201)
def add_source(
    project_id: UUID,
    body: SourceInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    from app.models import Project

    # Serialize duplicate registrations through the existing project lock.
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    url = correction_url(body.evidence_url)
    key = domain_key(url)
    row = db.scalar(
        select(SourceDomainExclusion)
        .where(SourceDomainExclusion.project_id == project_id, SourceDomainExclusion.domain == key)
        .with_for_update()
    )
    if row is None:
        row = SourceDomainExclusion(
            project_id=project_id,
            domain=key,
            reason=body.reason,
            evidence_url=url,
            created_by_user_id=user.id,
        )
        db.add(row)
    else:
        row.active = True
        row.reason = body.reason
        row.evidence_url = url
    row.history = [
        *(row.history or []),
        {
            "action": "REGISTER",
            "user_id": str(user.id),
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": body.reason,
            "evidence_url": url,
        },
    ]
    db.commit()
    db.refresh(row)
    return row


@router.post("/{rule_id}/deactivate")
def deactivate_source(
    project_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    row = db.scalar(
        select(SourceDomainExclusion)
        .where(SourceDomainExclusion.project_id == project_id, SourceDomainExclusion.id == rule_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "除外ドメインが見つかりません。")
    row.active = False
    row.history = [
        *(row.history or []),
        {
            "action": "DEACTIVATE",
            "user_id": str(user.id),
            "at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    db.commit()
    return {"active": False}
