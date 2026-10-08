from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CollectionJob, Company, ExternalPresenceEvidence, LeadSourceObservation, User
from app.project_access import company_access, project_access
from app.schema_core import Input
from app.schema_external_presence import PresenceSearchPlan
from app.security import current_user
from app.services.external_presence import capture_url, inventory
from app.services.presence_platforms import DOMAINS

router = APIRouter(prefix="/api")


@router.get("/collection-jobs/{job_id}/external-presence-report")
def presence_report(
    job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    job = db.get(CollectionJob, job_id)
    if job is None:
        raise HTTPException(404, "収集が見つかりません。")
    project_access(job.project_id, db, user, write=False)
    plan = PresenceSearchPlan.model_validate(job.presence_search_plan or {})
    required = [platform for platform in DOMAINS if plan.mode(platform) == "REQUIRED"]
    ids = select(LeadSourceObservation.company_id).where(
        LeadSourceObservation.collection_job_id == job.id
    )
    companies = db.scalars(
        select(Company).where(Company.project_id == job.project_id, Company.id.in_(ids))
    ).all()
    results = []
    for company in companies:
        rows = inventory(db, company.id)
        states = [
            r["status"]
            if r["status"] != "FOUND"
            or (
                r["observed_at"] is not None
                and r["observed_at"] >= datetime.now(timezone.utc) - timedelta(hours=24)
            )
            else "ERROR"
            for r in rows
            if r["platform"] in required
        ]
        state = (
            "NO_MATCH"
            if "NOT_FOUND" in states
            else "REVIEW_REQUIRED"
            if any(s != "FOUND" for s in states)
            else "MATCH"
        )
        results.append(dict(company_id=company.id, requirement_state=state, presences=rows))
    return dict(
        required_platforms=required,
        candidates=results,
        note="掲載の存在と現在募集中・活動中であることは別の条件です。送信権限ではありません。",
    )


@router.get("/companies/{company_id}/external-presences")
def get_presences(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company_access(company_id, db, user, write=False)
    return inventory(db, company_id)


@router.get("/projects/{project_id}/external-presence-evidence")
def get_evidence(
    project_id: UUID,
    company_id: UUID | None = None,
    unassigned: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    query = select(ExternalPresenceEvidence).where(
        ExternalPresenceEvidence.project_id == project_id
    )
    if company_id:
        company = company_access(company_id, db, user, write=False)
        if company.project_id != project_id:
            raise HTTPException(404, "根拠が見つかりません。")
        query = query.where(ExternalPresenceEvidence.company_id == company_id)
    if unassigned:
        linked_urls = select(ExternalPresenceEvidence.url).where(
            ExternalPresenceEvidence.project_id == project_id,
            ExternalPresenceEvidence.company_id.is_not(None),
        )
        query = query.where(
            ExternalPresenceEvidence.company_id.is_(None),
            ExternalPresenceEvidence.url.not_in(linked_urls),
        )
    rows = db.scalars(
        query.order_by(ExternalPresenceEvidence.observed_at.desc(), ExternalPresenceEvidence.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        dict(
            id=r.id,
            company_id=r.company_id,
            platform=r.platform,
            url=r.url,
            source_url=r.source_url,
            discovery_method=r.discovery_method,
            association=r.association,
            observed_at=r.observed_at,
        )
        for r in rows
    ]


class LinkEvidence(Input):
    company_id: UUID
    expected_url: str = Field(min_length=1, max_length=5000)
    confirmed: bool


@router.post("/external-presence-evidence/{evidence_id}/link")
def link_evidence(
    evidence_id: UUID,
    body: LinkEvidence,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(ExternalPresenceEvidence, evidence_id)
    if row is None:
        raise HTTPException(404, "根拠が見つかりません。")
    project_access(row.project_id, db, user)
    company = company_access(body.company_id, db, user)
    if company.project_id != row.project_id:
        raise HTTPException(404, "企業が見つかりません。")
    if not body.confirmed or body.expected_url != row.url:
        raise HTTPException(409, "関連を確認してから保存してください。")
    capture_url(
        db,
        row.project_id,
        row.url,
        row.source_url,
        company=company,
        method="PASSIVE",
        actor_user_id=user.id,
    )
    db.commit()
    return inventory(db, company.id)
