"""Human-owned source memory, with read access for project viewers."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
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


class CleanupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_ids: list[UUID] = Field(min_length=1, max_length=100)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime


@router.post("/cleanup")
def cleanup_sources(
    project_id: UUID,
    body: CleanupInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    from app.models import Company, Project
    from app.services.source_cleanup import cleanup

    project_access(project_id, db, user)
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    companies = db.scalars(
        select(Company)
        .where(Company.project_id == project_id, Company.id.in_(body.company_ids))
        .order_by(Company.id)
        .with_for_update()
    ).all()
    if len(companies) != len(set(body.company_ids)):
        raise HTTPException(404, "指定された企業が見つかりません。")
    result = cleanup(db, project_id, companies, user.id)
    db.commit()
    return result


@router.get("/cleanup/{company_id}")
def read_cleanup(
    project_id: UUID,
    company_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    from app.models import Company
    from app.services.source_cleanup import latest_event

    project_access(project_id, db, user, write=False)
    company = db.scalar(
        select(Company).where(Company.project_id == project_id, Company.id == company_id)
    )
    if company is None:
        raise HTTPException(404, "企業が見つかりません。")
    event = latest_event(db, company.id)
    return {
        "event": event,
        "restorable": bool(
            event
            and event.get("action") == "EXCLUDE"
            and company.status == "excluded"
            and event.get("after_updated_at") == company.updated_at.isoformat()
        ),
    }


@router.post("/cleanup/{company_id}/restore")
def restore_cleanup(
    project_id: UUID,
    company_id: UUID,
    body: RestoreInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    from app.models import Company
    from app.services.source_cleanup import restore

    project_access(project_id, db, user)
    company = db.scalar(
        select(Company)
        .where(Company.project_id == project_id, Company.id == company_id)
        .with_for_update()
    )
    if company is None:
        raise HTTPException(404, "企業が見つかりません。")
    restore(db, company, user.id, body.expected_updated_at)
    db.commit()
    return {"restored": True}
