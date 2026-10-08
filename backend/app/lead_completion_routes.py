"""Human inventory reads/refresh only; no network access, approval or delivery."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    ContactDestination,
    LeadDestinationLink,
    LeadSiteEvidence,
    LeadSourceObservation,
    Project,
    User,
)
from app.project_access import company_access, project_access
from app.security import current_user
from app.services.contact_destinations import candidates, linked_inventory, sync_company
from app.services.lead_identity import identity_hash
from app.services.sendability import evaluate as evaluate_sendability
from app.services.site_identity_review import confirmation, latest, public_review

router = APIRouter(prefix="/api")


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("/companies/{company_id}/sendability")
def sendability(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company = company_access(company_id, db, user, write=False)
    result = evaluate_sendability(db, company)
    try:
        project_access(company.project_id, db, user)
        result["can_review"] = True
    except HTTPException:
        result["can_review"] = False
    return result


@router.get("/companies/{company_id}/lead-completion")
def detail(company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company = company_access(company_id, db, user, write=False)
    try:
        project_access(company.project_id, db, user)
        can_refresh = True
    except HTTPException:
        can_refresh = False
    sites = db.scalars(
        select(LeadSiteEvidence)
        .where(LeadSiteEvidence.company_id == company.id)
        .order_by(LeadSiteEvidence.observed_at.desc(), LeadSiteEvidence.id)
        .limit(20)
    ).all()
    valid = confirmation(db, company)
    observations = db.scalars(
        select(LeadSourceObservation)
        .where(LeadSourceObservation.company_id == company.id)
        .order_by(LeadSourceObservation.observed_at.desc(), LeadSourceObservation.id)
        .limit(50)
    ).all()
    return {
        "company_id": company.id,
        "record_type": company.record_type,
        "identity_target": {
            "company_name": company.company_name,
            "address": company.address,
            "phone": company.phone,
            "website_url": company.website_url,
        },
        "expected_identity_hash": identity_hash(company),
        "identity_confirmation_source": valid,
        "human_identity_review": public_review(latest(db, company.id), company),
        "identity_status": "CONFIRMED" if valid else "REVIEW_REQUIRED",
        "official_site_confidence": "CONFIRMED" if valid else "REVIEW_REQUIRED",
        "site_evidence": [
            {
                "source_url": row.source_url,
                "confidence": row.confidence,
                "reasons": row.reasons,
                "current": row.identity_hash == identity_hash(company),
                "observed_at": row.observed_at,
            }
            for row in sites
        ],
        "observations": [
            {
                "id": row.id,
                "source": row.source,
                "observed_at": row.observed_at,
                "identity_status": row.identity_status,
                "identity_reasons": row.identity_reasons,
                "facts": row.facts,
                "applied_fields": row.applied_fields,
                "allowed_usage": row.allowed_usage,
                "terms_reference": row.terms_reference,
            }
            for row in observations
        ],
        "destinations": linked_inventory(db, company),
        "candidate_destination_count": len(candidates(db, company)),
        "can_refresh": can_refresh,
        "dm_ready": False,
        "execution_allowed": False,
        "qualification": "Phase A inventory only; DM readiness is not evaluated.",
    }


@router.post("/projects/{project_id}/lead-destinations/refresh")
def refresh(
    project_id: UUID,
    body: EmptyInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    db.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    companies = db.scalars(
        select(Company).where(Company.project_id == project_id).order_by(Company.id).limit(1001)
    ).all()
    if len(companies) > 1000:
        raise HTTPException(409, "今回は1000件以下のプロジェクトで窓口を整理してください。")
    for company in companies:
        sync_company(db, company)
    db.commit()
    unique = db.scalar(
        select(func.count())
        .select_from(ContactDestination)
        .where(
            ContactDestination.project_id == project_id,
            select(LeadDestinationLink.id)
            .where(LeadDestinationLink.destination_id == ContactDestination.id)
            .exists(),
        )
    )
    return {"leads": len(companies), "unique_destinations": unique, "execution_allowed": False}
