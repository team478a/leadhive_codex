"""Human evidence-bound draft preparation; no approval or send endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OutreachTemplate, Project, ProjectMember, User
from app.project_access import company_access
from app.security import current_user
from app.services import dm_preparation
from app.services.sendability import evaluate

router = APIRouter(prefix="/api/companies")


class PreparationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    template_id: UUID
    expected_template_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_destination_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_choice_version: int = Field(ge=1)
    source_url: str = Field(min_length=1, max_length=2048)
    fact: str = Field(min_length=10, max_length=500)
    evidence_excerpt: str = Field(min_length=10, max_length=2000)
    fact_observed: Literal[True]


@router.get("/{company_id}/dm-preparation")
def get_preparation(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company = company_access(company_id, db, user, write=False)
    project = db.get(Project, company.project_id)
    if project is None:
        raise HTTPException(404, "プロジェクトが見つかりません。")
    result = evaluate(db, company)
    templates = db.scalars(
        select(OutreachTemplate)
        .where(OutreachTemplate.project_id == project.id)
        .order_by(OutreachTemplate.name, OutreachTemplate.id)
        .limit(100)
    ).all()
    return dict(
        context_hash=dm_preparation.context(db, project),
        human_choice=result["human_choice"],
        can_prepare=project.user_id == user.id
        or db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
                ProjectMember.role == "editor",
            )
        )
        is not None,
        templates=[
            dict(
                id=t.id,
                name=t.name,
                channel=t.channel,
                subject=t.subject,
                body=t.body,
                hash=dm_preparation.template_hash(t),
            )
            for t in templates
        ],
        preparations=dm_preparation.list_preparations(db, company, project),
    )


@router.post("/{company_id}/dm-preparation", status_code=201)
def create_preparation(
    company_id: UUID,
    body: PreparationInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = company_access(company_id, db, user)
    project = db.scalar(select(Project).where(Project.id == company.project_id).with_for_update())
    db.refresh(company)
    return dm_preparation.prepare(db, company, project, user, body)
