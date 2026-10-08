"""Human-only stored-data preview and PENDING creation; never approve or send."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approval_routes import lock_preparation_sources, serialize
from app.database import get_db
from app.models import LeadDmPreparation, OutreachTemplate, Project, SmtpSettings, User
from app.project_access import company_access
from app.security import current_user
from app.services import dm_approval_preparation as service

router = APIRouter(prefix="/api/dm-preparations")


class PrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_preparation_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def owned(db, user, preparation_id, write=False):
    row = db.get(LeadDmPreparation, preparation_id)
    if row is None:
        raise HTTPException(404, "根拠付き下書きが見つかりません。")
    company = company_access(row.company_id, db, user, write=write)
    if company.project_id != row.project_id:
        raise HTTPException(404, "根拠付き下書きが見つかりません。")
    project = db.get(Project, row.project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if write:
        db.scalar(select(Project.id).where(Project.id == row.project_id).with_for_update())
        lock_preparation_sources(db, company, user)
        db.scalar(select(SmtpSettings).where(SmtpSettings.id == 1).with_for_update())
        db.scalar(
            select(OutreachTemplate)
            .where(OutreachTemplate.id == row.template_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        db.refresh(company)
    return row, company, project


@router.get("/{preparation_id}/approval-preview")
def preview(
    preparation_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    row, company, project = owned(db, user, preparation_id)
    return service.preview(db, row, company, project)


@router.post("/{preparation_id}/approval-request", status_code=201)
def prepare(
    preparation_id: UUID,
    body: PrepareInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row, company, project = owned(db, user, preparation_id, write=True)
    item = service.create(db, row, company, project, user, body.expected_preparation_hash)
    return serialize(db, item)
