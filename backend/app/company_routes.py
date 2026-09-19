import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import String, asc, cast, desc, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.analysis_routes import owned_company, owned_project
from app.database import get_db
from app.models import Activity, CollectionJob, Company, OperationJob, Project, User
from app.schemas import (
    ActivityInput,
    ActivityOut,
    CompanyBulkSalesInput,
    CompanyEditInput,
    CompanyMergeInput,
    CompanyOut,
    CompanyPageOut,
    CompanySalesInput,
    DashboardOut,
    DataQualityOut,
    DataQualityReanalyzeInput,
    DuplicateCandidateOut,
    OperationJobOut,
)
from app.security import current_user

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
    owned_project(project_id, db, user)
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
    owned_project(project_id, db, user)
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
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def company_query(
    project_id: UUID,
    rank: str | None,
    min_score: int | None,
    region: str | None,
    status: str | None,
    source: str | None,
    keyword: str | None,
    sort: str,
):
    query = select(Company).where(Company.project_id == project_id)
    if rank:
        query = query.where(Company.rank == rank)
    if min_score is not None:
        query = query.where(Company.score >= min_score)
    if region:
        query = query.where(
            or_(Company.prefecture.ilike(f"%{region}%"), Company.address.ilike(f"%{region}%"))
        )
    if status:
        query = query.where(Company.status == status)
    if source:
        query = query.where(Company.source == source)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            or_(
                Company.company_name.ilike(pattern),
                Company.business_type.ilike(pattern),
                Company.ai_summary.ilike(pattern),
                Company.source_keyword.ilike(pattern),
            )
        )
    if sort == "score_desc":
        return query.order_by(Company.score.desc().nullslast(), Company.created_at.desc())
    if sort == "company_name":
        return query.order_by(asc(Company.company_name), Company.id)
    return query.order_by(desc(Company.created_at), Company.id)


@router.get("/projects/{project_id}/company-list", response_model=CompanyPageOut)
def list_company_details(
    project_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    rank: Literal["A", "B", "C", "対象外"] | None = None,
    min_score: int | None = Query(None, ge=0, le=100),
    region: str | None = Query(None, max_length=100),
    status: Literal[
        "unreviewed", "target", "approached", "replied", "meeting", "won", "lost", "excluded"
    ]
    | None = None,
    source: Literal["serper", "google_places", "url", "csv"] | None = None,
    keyword: str | None = Query(None, max_length=200),
    sort: Literal["score_desc", "newest", "company_name"] = "score_desc",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    query = company_query(project_id, rank, min_score, region, status, source, keyword, sort)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = db.scalars(query.offset(offset).limit(limit)).all()
    return CompanyPageOut(items=items, total=total, offset=offset, limit=limit)


@router.get("/companies/{company_id}", response_model=CompanyOut)
def get_company(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return owned_company(company_id, db, user)


@router.patch("/companies/{company_id}/sales", response_model=CompanyOut)
def update_company_sales(
    company_id: UUID,
    body: CompanySalesInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    if company.status != body.status:
        db.add(
            Activity(
                company_id=company.id,
                activity_type="status_change",
                note=f"営業状況を {company.status} から {body.status} に変更",
            )
        )
    company.status = body.status
    company.notes = body.notes
    company.next_followup_at = body.next_followup_at
    db.commit()
    db.refresh(company)
    return company


@router.put("/companies/{company_id}", response_model=CompanyOut)
def edit_company(
    company_id: UUID,
    body: CompanyEditInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    for key, value in body.model_dump().items():
        setattr(company, key, value)
    db.commit()
    db.refresh(company)
    return company


@router.patch("/projects/{project_id}/companies/bulk-sales", response_model=list[CompanyOut])
def bulk_update_sales(
    project_id: UUID,
    body: CompanyBulkSalesInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    companies = db.scalars(
        select(Company).where(Company.project_id == project_id, Company.id.in_(body.company_ids))
    ).all()
    if len(companies) != len(set(body.company_ids)):
        raise HTTPException(404, "指定された企業が見つかりません。")
    for company in companies:
        if company.status != body.status:
            db.add(
                Activity(
                    company_id=company.id,
                    activity_type="status_change",
                    note=f"営業状況を {company.status} から {body.status} に変更",
                )
            )
            company.status = body.status
    db.commit()
    for company in companies:
        db.refresh(company)
    return companies


@router.get("/companies/{company_id}/activities", response_model=list[ActivityOut])
def list_activities(
    company_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_company(company_id, db, user)
    return db.scalars(
        select(Activity)
        .where(Activity.company_id == company_id)
        .order_by(Activity.created_at.desc(), Activity.id)
        .limit(100)
    ).all()


@router.post("/companies/{company_id}/activities", response_model=ActivityOut, status_code=201)
def add_activity(
    company_id: UUID,
    body: ActivityInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    activity = Activity(company_id=company.id, **body.model_dump())
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@router.get("/projects/{project_id}/companies.csv")
def export_companies(
    project_id: UUID,
    rank: Literal["A", "B", "C", "対象外"] | None = None,
    min_score: int | None = Query(None, ge=0, le=100),
    region: str | None = Query(None, max_length=100),
    status: str | None = None,
    source: str | None = None,
    keyword: str | None = Query(None, max_length=200),
    sort: Literal["score_desc", "newest", "company_name"] = "score_desc",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    companies = db.scalars(
        company_query(project_id, rank, min_score, region, status, source, keyword, sort)
    ).all()
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    fields = [
        "rank",
        "score",
        "company_name",
        "business_type",
        "prefecture",
        "city",
        "address",
        "website_url",
        "phone",
        "email",
        "contact_url",
        "instagram_url",
        "x_url",
        "ai_summary",
        "ai_reason",
        "ai_strengths",
        "ai_concerns",
        "ai_recommended_approach",
        "status",
        "notes",
        "source",
        "source_keyword",
    ]
    writer.writerow(fields)
    for company in companies:
        row = []
        for field in fields:
            value = getattr(company, field)
            if isinstance(value, list):
                value = " / ".join(value)
            row.append(csv_safe(value))
        writer.writerow(row)
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leadhive-companies.csv"'},
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_ids = select(Project.id).where(Project.user_id == user.id)
    total = db.scalar(
        select(func.count()).select_from(Company).where(Company.project_id.in_(owned_ids))
    )
    rank_rows = db.execute(
        select(cast(Company.rank, String), func.count())
        .where(Company.project_id.in_(owned_ids), Company.rank.is_not(None))
        .group_by(Company.rank)
    ).all()
    status_rows = db.execute(
        select(Company.status, func.count())
        .where(Company.project_id.in_(owned_ids))
        .group_by(Company.status)
    ).all()
    jobs = db.scalars(
        select(CollectionJob)
        .join(Project, Project.id == CollectionJob.project_id)
        .where(Project.user_id == user.id)
        .order_by(CollectionJob.created_at.desc(), CollectionJob.id)
        .limit(5)
    ).all()
    operation_rows = db.execute(
        select(OperationJob.status, func.count())
        .join(Project, Project.id == OperationJob.project_id)
        .where(Project.user_id == user.id)
        .group_by(OperationJob.status)
    ).all()
    unread_failures = db.scalar(
        select(func.count())
        .select_from(OperationJob)
        .join(Project, Project.id == OperationJob.project_id)
        .where(
            Project.user_id == user.id,
            OperationJob.status == "failed",
            OperationJob.acknowledged_at.is_(None),
        )
    )
    operations = db.scalars(
        select(OperationJob)
        .join(Project, Project.id == OperationJob.project_id)
        .where(Project.user_id == user.id)
        .order_by(OperationJob.created_at.desc(), OperationJob.id)
        .limit(10)
    ).all()
    return DashboardOut(
        total_companies=total or 0,
        ranks={key: count for key, count in rank_rows},
        statuses={key: count for key, count in status_rows},
        recent_jobs=jobs,
        operation_statuses={key: count for key, count in operation_rows},
        unread_operation_failures=unread_failures or 0,
        recent_operations=operations,
    )
