"""Human-only site identity confirmation; never retrieves a site or approves sending."""

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, SiteIdentityReviewEvent, User
from app.project_access import company_access
from app.security import current_user
from app.services.lead_identity import compare, identity_hash, normalize
from app.services.site_identity_review import latest, official_evidence_url, public_review

router = APIRouter(prefix="/api/companies")


class IdentityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_review_version: int = Field(ge=0)
    source_url: str = Field(min_length=1, max_length=2048)
    observed_name: str = Field(min_length=2, max_length=300)
    observed_address: str = Field(default="", max_length=1000)
    observed_phone: str = Field(default="", max_length=100)
    evidence_excerpt: str = Field(min_length=10, max_length=1000)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_review_version: int = Field(ge=1)


def lock_company(db, user, company_id):
    company = company_access(company_id, db, user)
    db.scalar(select(Project.id).where(Project.id == company.project_id).with_for_update())
    db.refresh(company)
    return company


@router.post("/{company_id}/site-identity-reviews", status_code=201)
def confirm(
    company_id: UUID,
    body: IdentityInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = lock_company(db, user, company_id)
    previous = latest(db, company.id)
    digest = identity_hash(company)
    if (
        digest != body.expected_hash
        or (previous.version if previous else 0) != body.expected_review_version
    ):
        raise HTTPException(409, "確認対象または確認記録が変わりました。再読込してください。")
    try:
        source = official_evidence_url(company, body.source_url)
    except (ValueError, UnicodeError):
        raise HTTPException(
            422,
            "根拠URLには公式サイト内の公開ページを指定してください。秘密情報・クエリ等は含められません。",
        ) from None
    incoming = SimpleNamespace(
        record_type=company.record_type,
        company_name=body.observed_name,
        address=body.observed_address,
        phone=body.observed_phone,
        website_url=company.website_url,
    )
    if body.observed_phone and not re.fullmatch(r"[0-9]{9,15}", normalize(body.observed_phone)):
        raise HTTPException(422, "電話は9〜15桁の番号を確認してください。")
    if body.observed_address and len(normalize(body.observed_address)) < 6:
        raise HTTPException(422, "住所は番地を含む住所全体を確認してください。")
    result, reasons = compare(company, incoming)
    if len(normalize(body.observed_name)) < 2 or result != "CONFIRMED":
        raise HTTPException(
            422,
            "名称と、番地を含む住所または電話の一致が必要です。矛盾や地域名だけでは確認できません。",
        )
    now = datetime.now(timezone.utc)
    row = SiteIdentityReviewEvent(
        project_id=company.project_id,
        company_id=company.id,
        actor_user_id=user.id,
        version=(previous.version if previous else 0) + 1,
        event_type="CONFIRMED",
        identity_hash=digest,
        source_url=source,
        observed_name=body.observed_name,
        observed_address=body.observed_address,
        observed_phone=body.observed_phone,
        evidence_excerpt=body.evidence_excerpt,
        reasons=reasons,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    db.add(row)
    db.commit()
    return {"review": public_review(row, company), "execution_allowed": False}


@router.post("/{company_id}/site-identity-reviews/revoke", status_code=201)
def revoke(
    company_id: UUID,
    body: RevokeInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = lock_company(db, user, company_id)
    previous = latest(db, company.id)
    if (
        previous is None
        or previous.version != body.expected_review_version
        or previous.event_type == "REVOKED"
    ):
        raise HTTPException(409, "確認記録が変わりました。再読込してください。")
    now = datetime.now(timezone.utc)
    row = SiteIdentityReviewEvent(
        project_id=company.project_id,
        company_id=company.id,
        actor_user_id=user.id,
        version=previous.version + 1,
        event_type="REVOKED",
        identity_hash=previous.identity_hash,
        source_url=previous.source_url,
        observed_name=previous.observed_name,
        observed_address=previous.observed_address,
        observed_phone=previous.observed_phone,
        evidence_excerpt=previous.evidence_excerpt,
        reasons=previous.reasons,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    db.add(row)
    db.commit()
    return {"review": public_review(row, company), "execution_allowed": False}
