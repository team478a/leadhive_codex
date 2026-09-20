import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import String, asc, cast, desc, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.analysis_routes import owned_company, owned_project
from app.database import get_db
from app.models import (
    Activity,
    CollectionJob,
    Company,
    OperationJob,
    Project,
    SavedCompanyFilter,
    User,
)
from app.schemas import (
    ActivityInput,
    ActivityOut,
    AssigneeAnalyticsOut,
    CompanyBulkAssigneeInput,
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
    SalesActivityAnalyticsOut,
    SalesAnalyticsAssigneeOut,
    SavedCompanyFilterInput,
    SavedCompanyFilterOut,
)
from app.security import current_user

router = APIRouter(prefix="/api")
JST = ZoneInfo("Asia/Tokyo")


def status_transition_count(status: str):
    return func.count().filter(
        Activity.activity_type == "status_change",
        Activity.note.like(f"% から {status} に変更"),
    )


@router.get("/sales-activity-analytics", response_model=SalesActivityAnalyticsOut)
def sales_activity_analytics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = (
        select(
            func.count(),
            status_transition_count("approached"),
            status_transition_count("replied"),
            status_transition_count("meeting"),
            status_transition_count("won"),
        )
        .select_from(Activity)
        .join(Company, Company.id == Activity.company_id)
        .join(Project, Project.id == Company.project_id)
        .where(Project.user_id == user.id, Activity.created_at >= since)
    )
    activities, approached, replied, meetings, won = db.execute(base).one()
    rows = db.execute(
        select(
            Company.assignee,
            status_transition_count("approached"),
            status_transition_count("replied"),
            status_transition_count("meeting"),
            status_transition_count("won"),
        )
        .select_from(Activity)
        .join(Company, Company.id == Activity.company_id)
        .join(Project, Project.id == Company.project_id)
        .where(Project.user_id == user.id, Activity.created_at >= since)
        .group_by(Company.assignee)
        .order_by(status_transition_count("won").desc(), Company.assignee)
    ).all()
    denominator = approached or 0
    return SalesActivityAnalyticsOut(
        days=days,
        activities=activities,
        approached=approached,
        replied=replied,
        meetings=meetings,
        won=won,
        reply_rate=round(replied / denominator * 100, 1) if denominator else 0,
        meeting_rate=round(meetings / denominator * 100, 1) if denominator else 0,
        win_rate=round(won / denominator * 100, 1) if denominator else 0,
        by_assignee=[
            SalesAnalyticsAssigneeOut(
                assignee=assignee or "未設定",
                approached=row_approached,
                replied=row_replied,
                meetings=row_meetings,
                won=row_won,
            )
            for assignee, row_approached, row_replied, row_meetings, row_won in rows
        ],
    )


@router.get(
    "/projects/{project_id}/saved-company-filters", response_model=list[SavedCompanyFilterOut]
)
def list_saved_company_filters(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    owned_project(project_id, db, user)
    return db.scalars(
        select(SavedCompanyFilter)
        .where(SavedCompanyFilter.project_id == project_id)
        .order_by(SavedCompanyFilter.created_at, SavedCompanyFilter.id)
    ).all()


@router.post(
    "/projects/{project_id}/saved-company-filters",
    response_model=SavedCompanyFilterOut,
    status_code=201,
)
def create_saved_company_filter(
    project_id: UUID,
    body: SavedCompanyFilterInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    item = SavedCompanyFilter(
        project_id=project_id, name=body.name, filters=body.filters.model_dump()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/saved-company-filters/{filter_id}", response_model=SavedCompanyFilterOut)
def update_saved_company_filter(
    filter_id: UUID,
    body: SavedCompanyFilterInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    item = db.scalar(
        select(SavedCompanyFilter)
        .join(Project, Project.id == SavedCompanyFilter.project_id)
        .where(SavedCompanyFilter.id == filter_id, Project.user_id == user.id)
    )
    if item is None:
        raise HTTPException(404, "保存フィルターが見つかりません。")
    item.name = body.name
    item.filters = body.filters.model_dump()
    db.commit()
    db.refresh(item)
    return item


@router.delete("/saved-company-filters/{filter_id}", status_code=204)
def delete_saved_company_filter(
    filter_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    item = db.scalar(
        select(SavedCompanyFilter)
        .join(Project, Project.id == SavedCompanyFilter.project_id)
        .where(SavedCompanyFilter.id == filter_id, Project.user_id == user.id)
    )
    if item is None:
        raise HTTPException(404, "保存フィルターが見つかりません。")
    db.delete(item)
    db.commit()


@router.get("/projects/{project_id}/assignee-analytics", response_model=list[AssigneeAnalyticsOut])
def assignee_analytics(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    owned_project(project_id, db, user)
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(
            Company.assignee,
            func.count(),
            func.count().filter(Company.status == "approached"),
            func.count().filter(Company.status == "replied"),
            func.count().filter(Company.status == "meeting"),
            func.count().filter(Company.status == "won"),
            func.count().filter(Company.next_followup_at < now),
        )
        .where(Company.project_id == project_id)
        .group_by(Company.assignee)
        .order_by(func.count().desc(), Company.assignee)
    ).all()
    return [
        AssigneeAnalyticsOut(
            assignee=assignee or "未設定",
            total=total,
            approached=approached,
            replied=replied,
            meetings=meetings,
            won=won,
            overdue=overdue,
        )
        for assignee, total, approached, replied, meetings, won, overdue in rows
    ]


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
    assignee: str | None,
    followup: str | None,
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
    if assignee:
        query = query.where(Company.assignee.ilike(f"%{assignee}%"))
    now = datetime.now(timezone.utc)
    if followup == "overdue":
        query = query.where(Company.next_followup_at < now)
    elif followup == "today":
        day_start = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(
            Company.next_followup_at >= day_start,
            Company.next_followup_at < day_start + timedelta(days=1),
        )
    elif followup == "upcoming":
        query = query.where(Company.next_followup_at >= now)
    elif followup == "unset":
        query = query.where(Company.next_followup_at.is_(None))
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
    assignee: str | None = Query(None, max_length=200),
    followup: Literal["overdue", "today", "upcoming", "unset"] | None = None,
    sort: Literal["score_desc", "newest", "company_name"] = "score_desc",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    query = company_query(
        project_id, rank, min_score, region, status, source, keyword, assignee, followup, sort
    )
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
    values = body.model_dump()
    protected_fields = values.pop("protected_fields")
    for key, value in values.items():
        setattr(company, key, value)
    company.protected_fields = list(dict.fromkeys(protected_fields))
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


@router.patch("/projects/{project_id}/companies/bulk-assignee", response_model=list[CompanyOut])
def bulk_update_assignee(
    project_id: UUID,
    body: CompanyBulkAssigneeInput,
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
        if company.assignee != body.assignee:
            db.add(
                Activity(
                    company_id=company.id,
                    activity_type="note",
                    note=(
                        f"担当者を「{company.assignee or '未設定'}」から"
                        f"「{body.assignee or '未設定'}」へ変更"
                    ),
                )
            )
            company.assignee = body.assignee
    db.commit()
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
    assignee: str | None = Query(None, max_length=200),
    followup: Literal["overdue", "today", "upcoming", "unset"] | None = None,
    sort: Literal["score_desc", "newest", "company_name"] = "score_desc",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    companies = db.scalars(
        company_query(
            project_id, rank, min_score, region, status, source, keyword, assignee, followup, sort
        )
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
        "assignee",
        "next_followup_at",
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
    now = datetime.now(timezone.utc)
    today_start = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    overdue_followups = (
        db.scalar(
            select(func.count())
            .select_from(Company)
            .where(Company.project_id.in_(owned_ids), Company.next_followup_at < now)
        )
        or 0
    )
    due_today_followups = (
        db.scalar(
            select(func.count())
            .select_from(Company)
            .where(
                Company.project_id.in_(owned_ids),
                Company.next_followup_at >= today_start,
                Company.next_followup_at < today_start + timedelta(days=1),
            )
        )
        or 0
    )
    return DashboardOut(
        total_companies=total or 0,
        ranks={key: count for key, count in rank_rows},
        statuses={key: count for key, count in status_rows},
        recent_jobs=jobs,
        operation_statuses={key: count for key, count in operation_rows},
        unread_operation_failures=unread_failures or 0,
        recent_operations=operations,
        overdue_followups=overdue_followups,
        due_today_followups=due_today_followups,
    )
