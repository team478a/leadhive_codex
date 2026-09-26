"""Company deduplication and data-quality HTTP endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import (
    Activity,
    Company,
    ContactPerson,
    OperationJob,
    User,
)
from app.project_access import project_access as owned_project
from app.schemas import (
    CompanyMergeInput,
    CompanyOut,
    DataQualityOut,
    DataQualityReanalyzeInput,
    DuplicateCandidateOut,
    OperationJobOut,
)
from app.security import current_user
from app.services.operations import add_operation_job

router = APIRouter(prefix="/api")


def duplicate_reasons(first: Company, second: Company) -> list[str]:
    reasons = []
    if first.email and first.email.lower() == second.email.lower():
        reasons.append("email")
    if first.phone and first.phone == second.phone:
        reasons.append("phone")
    if (
        first.address
        and first.company_name.lower() == second.company_name.lower()
        and first.address.lower() == second.address.lower()
    ):
        reasons.append("name_address")
    return reasons


@router.get(
    "/projects/{project_id}/duplicate-candidates", response_model=list[DuplicateCandidateOut]
)
def duplicate_candidates(
    project_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user, write=False)
    left = aliased(Company)
    right = aliased(Company)
    email_match = (left.email != "") & (func.lower(left.email) == func.lower(right.email))
    phone_match = (left.phone != "") & (left.phone == right.phone)
    name_address_match = (
        (left.address != "")
        & (func.lower(left.company_name) == func.lower(right.company_name))
        & (func.lower(left.address) == func.lower(right.address))
    )
    rows = db.execute(
        select(left, right)
        .where(
            left.project_id == project_id,
            right.project_id == project_id,
            left.id < right.id,
            or_(email_match, phone_match, name_address_match),
        )
        .order_by(left.created_at, right.created_at)
        .limit(limit)
    ).all()
    result = []
    for first, second in rows:
        result.append(
            DuplicateCandidateOut(
                left=first, right=second, reasons=duplicate_reasons(first, second)
            )
        )
    return result


@router.post("/projects/{project_id}/companies/merge", response_model=CompanyOut)
def merge_companies(
    project_id: UUID,
    body: CompanyMergeInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    if body.target_id == body.source_id:
        raise HTTPException(422, "異なる企業を指定してください。")
    companies = db.scalars(
        select(Company).where(
            Company.project_id == project_id,
            Company.id.in_((body.target_id, body.source_id)),
        )
    ).all()
    if len(companies) != 2:
        raise HTTPException(404, "統合対象の企業が見つかりません。")
    by_id = {item.id: item for item in companies}
    target, source = by_id[body.target_id], by_id[body.source_id]
    if not duplicate_reasons(target, source):
        raise HTTPException(409, "一致する重複根拠がないため統合できません。")
    fill_fields = (
        "address",
        "phone",
        "email",
        "prefecture",
        "city",
        "contact_url",
        "instagram_url",
        "x_url",
        "tiktok_url",
        "facebook_url",
        "youtube_url",
        "line_url",
        "business_summary",
        "website_text",
        "business_type",
        "ai_summary",
        "ai_reason",
        "ai_recommended_approach",
    )
    for field in fill_fields:
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
    if source.notes and source.notes not in target.notes:
        target.notes = "\n\n".join(value for value in (target.notes, source.notes) if value)
    if target.next_followup_at is None:
        target.next_followup_at = source.next_followup_at
    website_url, domain = source.website_url, source.domain
    db.execute(
        update(Activity).where(Activity.company_id == source.id).values(company_id=target.id)
    )
    db.execute(
        update(ContactPerson)
        .where(ContactPerson.company_id == source.id)
        .values(company_id=target.id)
    )
    db.execute(
        update(Company)
        .where(Company.duplicate_of_id == source.id)
        .values(duplicate_of_id=target.id)
    )
    db.delete(source)
    db.flush()
    if target.website_url is None and website_url:
        target.website_url, target.domain = website_url, domain
    db.add(
        Activity(
            company_id=target.id,
            activity_type="note",
            note=f"重複企業「{source.company_name}」を統合しました。",
        )
    )
    db.commit()
    db.refresh(target)
    return target


def stale_condition(cutoff: datetime):
    return (Company.analysis_status == "completed") & (
        Company.scraped_at.is_(None) | (Company.scraped_at < cutoff)
    )


@router.get("/projects/{project_id}/data-quality", response_model=DataQualityOut)
def data_quality(
    project_id: UUID,
    stale_days: int = Query(90, ge=1, le=3650),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user, write=False)
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    base = Company.project_id == project_id
    row = db.execute(
        select(
            func.count(),
            func.count().filter(Company.website_url.is_(None)),
            func.count().filter(Company.address == ""),
            func.count().filter(Company.phone == ""),
            func.count().filter(Company.email == ""),
            func.count().filter(
                (Company.phone == "") & (Company.email == "") & (Company.contact_url == "")
            ),
            func.count().filter(Company.analysis_status == "failed"),
            func.count().filter(stale_condition(cutoff)),
            func.count().filter(
                Company.website_url.is_not(None)
                & ((Company.analysis_status == "failed") | stale_condition(cutoff))
            ),
        ).where(base)
    ).one()
    return DataQualityOut(
        total=row[0],
        missing_website=row[1],
        missing_address=row[2],
        missing_phone=row[3],
        missing_email=row[4],
        missing_contact=row[5],
        failed_analysis=row[6],
        stale_analysis=row[7],
        reanalyzable=row[8],
        stale_days=stale_days,
    )


@router.post(
    "/projects/{project_id}/data-quality/reanalyze",
    response_model=OperationJobOut,
    status_code=202,
)
def reanalyze_data_quality(
    project_id: UUID,
    body: DataQualityReanalyzeInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "web_analysis",
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        raise HTTPException(409, "Web解析がすでに実行待ちです。")
    cutoff = datetime.now(timezone.utc) - timedelta(days=body.stale_days)
    condition = Company.analysis_status == "failed"
    if body.scope == "stale":
        condition = stale_condition(cutoff)
    elif body.scope == "failed_or_stale":
        condition = condition | stale_condition(cutoff)
    company_ids = list(
        db.scalars(
            select(Company.id)
            .where(
                Company.project_id == project_id,
                Company.website_url.is_not(None),
                condition,
            )
            .order_by(Company.updated_at, Company.id)
            .limit(100)
        ).all()
    )
    if not company_ids:
        raise HTTPException(409, "再解析対象の企業はありません。")
    job = OperationJob(
        project_id=project_id,
        operation_type="web_analysis",
        payload={"company_ids": [str(item) for item in company_ids], "force": True},
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "Web解析がすでに実行待ちです。")
    db.commit()
    db.refresh(job)
    return job
