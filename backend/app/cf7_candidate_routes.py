"""Controlled candidate preparation only. No observation upload or send endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approval_routes import lock_preparation_sources, preparation_source, serialize
from app.database import get_db
from app.models import CF7Observation, User
from app.schema_approval import FormPreparation, StrictInput
from app.security import current_user
from app.services import cf7_candidate_preparation as service
from app.services.cf7_candidate_contract import Selection

router = APIRouter(prefix="/api", tags=["Non-executable CF7 candidates"])


class ConsentSelection(Selection):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,99}$")


class Choices(StrictInput):
    selections: list[ConsentSelection] = Field(max_length=20)


class Prepare(Choices, FormPreparation):
    pass


def sources(db, draft_id, user):
    service.ensure_enabled()
    company, draft = preparation_source(db, draft_id, user)
    lock_preparation_sources(db, company, user)
    db.scalars(
        select(CF7Observation)
        .where(CF7Observation.company_id == company.id)
        .order_by(CF7Observation.id)
        .with_for_update()
    ).all()
    return company, draft


@router.get("/cf7-candidate-preparation-status")
def status(user: User = Depends(current_user)):
    return {"enabled": service.enabled(), "non_executable": True}


@router.get("/outreach-drafts/{draft_id}/cf7-candidate-preview")
def preview(draft_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company, draft = sources(db, draft_id, user)
    return service.preparation(db, company, draft)[1]


@router.post("/outreach-drafts/{draft_id}/cf7-candidate-preview")
def selected_preview(
    draft_id: UUID, body: Choices, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company, draft = sources(db, draft_id, user)
    return service.preparation(db, company, draft, body.selections)[1]


@router.post("/outreach-drafts/{draft_id}/cf7-candidate-request", status_code=201)
def prepare(
    draft_id: UUID, body: Prepare, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company, draft = sources(db, draft_id, user)
    return serialize(
        db,
        service.create_request(
            db, company, draft, body.selections, body.expected_preparation_hash, user
        ),
    )
