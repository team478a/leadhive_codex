"""Human-only choice of READY preparation destinations; no approval or dispatch."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DestinationChoiceEvent, Project, User
from app.project_access import company_access
from app.security import current_user
from app.services.destination_choice import latest, public_choice
from app.services.sendability import evaluate

router = APIRouter(prefix="/api/companies")


class ChoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_purpose_version: int = Field(ge=1)
    expected_choice_version: int = Field(ge=0)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_choice_version: int = Field(ge=1)


def locked_company(db, user, company_id):
    company = company_access(company_id, db, user)
    db.scalar(select(Project.id).where(Project.id == company.project_id).with_for_update())
    db.refresh(company)
    return company


@router.post("/{company_id}/destinations/{destination_id}/choice", status_code=201)
def choose(
    company_id: UUID,
    destination_id: UUID,
    body: ChoiceInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = locked_company(db, user, company_id)
    previous = latest(db, company.id)
    result = evaluate(db, company)
    item = next((d for d in result["destinations"] if d["id"] == destination_id), None)
    if (
        item is None
        or item["status"] != "READY"
        or item["expected_hash"] != body.expected_hash
        or item["review"]["version"] != body.expected_purpose_version
        or (previous.version if previous else 0) != body.expected_choice_version
    ):
        raise HTTPException(
            409,
            "窓口・用途・選択記録または安全条件が変わりました。READYの窓口を再確認してください。",
        )
    now = datetime.now(timezone.utc)
    if item["review"]["expires_at"] <= now:
        raise HTTPException(409, "用途確認の期限が切れました。再確認してください。")
    row = DestinationChoiceEvent(
        project_id=company.project_id,
        company_id=company.id,
        destination_id=destination_id,
        actor_user_id=user.id,
        version=(previous.version if previous else 0) + 1,
        event_type="SELECTED",
        destination_type=item["type"],
        destination=item["destination"],
        snapshot_hash=item["expected_hash"],
        purpose_review_version=body.expected_purpose_version,
        created_at=now,
        expires_at=min(now + timedelta(days=7), item["review"]["expires_at"]),
    )
    db.add(row)
    db.commit()
    return public_choice(db, company, result["destinations"])


@router.post("/{company_id}/destination-choice/revoke", status_code=201)
def revoke(
    company_id: UUID,
    body: RevokeInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = locked_company(db, user, company_id)
    previous = latest(db, company.id)
    if (
        previous is None
        or previous.version != body.expected_choice_version
        or previous.event_type == "REVOKED"
    ):
        raise HTTPException(409, "選択記録が変わりました。再読込してください。")
    now = datetime.now(timezone.utc)
    row = DestinationChoiceEvent(
        project_id=company.project_id,
        company_id=company.id,
        destination_id=previous.destination_id,
        actor_user_id=user.id,
        version=previous.version + 1,
        event_type="REVOKED",
        destination_type=previous.destination_type,
        destination=previous.destination,
        snapshot_hash=previous.snapshot_hash,
        purpose_review_version=previous.purpose_review_version,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    db.add(row)
    db.commit()
    return public_choice(db, company, evaluate(db, company)["destinations"])
