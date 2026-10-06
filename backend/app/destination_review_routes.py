"""Human-only append-only purpose reviews. Independent of sending approval."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    ContactDestination,
    DestinationReviewEvent,
    LeadDestinationLink,
    Project,
    User,
)
from app.project_access import company_access
from app.security import current_user
from app.services.collection import canonicalize_url
from app.services.contact_destinations import candidates, normalize_destination
from app.services.destination_review import latest, public_review, snapshot_hash

router = APIRouter(prefix="/api/companies")


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_review_version: int = Field(ge=0)
    purpose: Literal[
        "general",
        "business",
        "partnership",
        "sales",
        "support",
        "recruitment",
        "reservation",
        "unknown",
    ]
    scope: Literal["company", "location", "group", "unknown"]
    source_url: str = Field(min_length=1, max_length=2048)
    evidence_excerpt: str = Field(min_length=10, max_length=1000)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_review_version: int = Field(ge=1)


def locked_pair(db, user, company_id, destination_id):
    company = company_access(company_id, db, user)
    # Serializes review versions and inventory refresh; never locks/reserves dispatch.
    db.scalar(select(Project.id).where(Project.id == company.project_id).with_for_update())
    db.refresh(company)
    destination = db.scalar(
        select(ContactDestination)
        .join(LeadDestinationLink, LeadDestinationLink.destination_id == ContactDestination.id)
        .where(
            ContactDestination.id == destination_id,
            ContactDestination.project_id == company.project_id,
            LeadDestinationLink.company_id == company.id,
            ContactDestination.active.is_(True),
        )
    )
    if destination is None or (
        destination.destination_type,
        destination.destination,
    ) not in candidates(db, company):
        raise HTTPException(409, "窓口候補が変わりました。候補を整理して再確認してください。")
    return company, destination


@router.post("/{company_id}/destinations/{destination_id}/reviews", status_code=201)
def confirm(
    company_id: UUID,
    destination_id: UUID,
    body: ReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company, destination = locked_pair(db, user, company_id, destination_id)
    previous = latest(db, company.id, destination.id)
    digest = snapshot_hash(db, company, destination)
    if (
        digest != body.expected_hash
        or (previous.version if previous else 0) != body.expected_review_version
    ):
        raise HTTPException(409, "確認対象または確認記録が変わりました。再読込してください。")
    try:
        parsed = urlsplit(body.source_url)
        source = normalize_destination("form", body.source_url)
        if (
            parsed.query
            or parsed.fragment
            or canonicalize_url(source)[1] != canonicalize_url(company.website_url)[1]
        ):
            raise ValueError("Evidence must be a public official-site URL")
    except (ValueError, UnicodeError):
        raise HTTPException(
            422,
            "根拠URLには公式サイト内の公開ページを指定してください。認証情報・クエリ・フラグメントは含められません。",
        ) from None
    now = datetime.now(timezone.utc)
    row = DestinationReviewEvent(
        project_id=company.project_id,
        company_id=company.id,
        destination_id=destination.id,
        actor_user_id=user.id,
        version=(previous.version if previous else 0) + 1,
        event_type="CONFIRMED",
        purpose=body.purpose,
        scope=body.scope,
        source_url=source,
        evidence_excerpt=body.evidence_excerpt,
        snapshot_hash=digest,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    db.add(row)
    db.commit()
    return {"review": public_review(row, digest), "execution_allowed": False}


@router.post("/{company_id}/destinations/{destination_id}/reviews/revoke", status_code=201)
def revoke(
    company_id: UUID,
    destination_id: UUID,
    body: RevokeInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company, destination = locked_pair(db, user, company_id, destination_id)
    previous = latest(db, company.id, destination.id)
    if (
        previous is None
        or previous.version != body.expected_review_version
        or previous.event_type == "REVOKED"
    ):
        raise HTTPException(409, "確認記録が変わりました。再読込してください。")
    now = datetime.now(timezone.utc)
    row = DestinationReviewEvent(
        project_id=company.project_id,
        company_id=company.id,
        destination_id=destination.id,
        actor_user_id=user.id,
        version=previous.version + 1,
        event_type="REVOKED",
        purpose=previous.purpose,
        scope=previous.scope,
        source_url=previous.source_url,
        evidence_excerpt=previous.evidence_excerpt,
        snapshot_hash=previous.snapshot_hash,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    db.add(row)
    db.commit()
    return {
        "review": public_review(row, snapshot_hash(db, company, destination)),
        "execution_allowed": False,
    }
