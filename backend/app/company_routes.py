import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import String, asc, case, cast, desc, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.analysis_routes import owned_company, owned_project
from app.database import get_db
from app.models import (
    Activity,
    CollectionJob,
    Company,
    ContactPerson,
    InboundEmail,
    OperationJob,
    OutreachConversion,
    OutreachDraft,
    OutreachDraftApproval,
    Project,
    SavedCompanyFilter,
    SuppressionEntry,
    User,
)
from app.project_access import accessible_project_condition
from app.schemas import (
    ActivityInput,
    ActivityOut,
    AssigneeAnalyticsOut,
    CompanyBulkAssigneeInput,
    CompanyBulkSalesInput,
    CompanyContactControlInput,
    CompanyEditInput,
    CompanyMergeInput,
    CompanyOut,
    CompanyPageOut,
    CompanySalesInput,
    ContactPersonInput,
    ContactPersonOut,
    DashboardOut,
    DataQualityOut,
    DataQualityReanalyzeInput,
    DuplicateCandidateOut,
    FollowupTaskOut,
    FollowupTaskResolveInput,
    OperationJobOut,
    OutreachEffectivenessAnalyticsOut,
    OutreachEffectivenessItemOut,
    OutreachQueueItemOut,
    OutreachRecordInput,
    ReplyQueueItemOut,
    ReplyResponseInput,
    SalesActivityAnalyticsOut,
    SalesAnalyticsAssigneeOut,
    SavedCompanyFilterInput,
    SavedCompanyFilterOut,
)
from app.security import current_user
from app.services.outreach_attribution import record_outreach_conversion

router = APIRouter(prefix="/api")
JST = ZoneInfo("Asia/Tokyo")


def outreach_channels(company: Company) -> list[str]:
    channels = []
    if company.email:
        channels.append("email")
    if company.contact_url:
        channels.append("form")
    if company.phone:
        channels.append("call")
    if any(
        (
            company.instagram_url,
            company.x_url,
            company.tiktok_url,
            company.facebook_url,
            company.line_url,
        )
    ):
        channels.append("sns")
    return channels


def outreach_due_state(company: Company, now: datetime) -> str:
    if company.next_followup_at is None:
        return "unset"
    day_start = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    if company.next_followup_at < now:
        return "overdue"
    if company.next_followup_at < day_start + timedelta(days=1):
        return "today"
    return "upcoming"


def owned_contact_person(contact_id: UUID, db: Session, user: User) -> ContactPerson:
    contact = db.get(ContactPerson, contact_id)
    if contact is None:
        raise HTTPException(404, "担当者情報が見つかりません。")
    owned_company(contact.company_id, db, user)
    return contact


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
        .where(accessible_project_condition(user.id), Activity.created_at >= since)
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
        .where(accessible_project_condition(user.id), Activity.created_at >= since)
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


@router.get("/outreach-effectiveness-analytics", response_model=OutreachEffectivenessAnalyticsOut)
def outreach_effectiveness_analytics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    approvals = func.count(OutreachDraftApproval.id)
    replied = func.count(func.distinct(OutreachConversion.approval_id)).filter(
        OutreachConversion.outcome == "replied"
    )
    meetings = func.count(func.distinct(OutreachConversion.approval_id)).filter(
        OutreachConversion.outcome == "meeting"
    )
    won = func.count(func.distinct(OutreachConversion.approval_id)).filter(
        OutreachConversion.outcome == "won"
    )
    rows = db.execute(
        select(
            OutreachDraftApproval.approval_type,
            OutreachDraftApproval.subject,
            approvals,
            replied,
            meetings,
            won,
        )
        .select_from(OutreachDraftApproval)
        .join(OutreachDraft, OutreachDraft.id == OutreachDraftApproval.draft_id)
        .join(Company, Company.id == OutreachDraft.company_id)
        .join(Project, Project.id == Company.project_id)
        .outerjoin(
            OutreachConversion, OutreachConversion.approval_id == OutreachDraftApproval.id
        )
        .where(
            accessible_project_condition(user.id),
            OutreachDraftApproval.delivered_at >= since,
        )
        .group_by(OutreachDraftApproval.approval_type, OutreachDraftApproval.subject)
        .order_by(approvals.desc(), OutreachDraftApproval.subject)
        .limit(100)
    ).all()
    return OutreachEffectivenessAnalyticsOut(
        days=days,
        items=[
            OutreachEffectivenessItemOut(
                approval_type=approval_type,
                subject=subject,
                approvals=approvals,
                replied=row_replied,
                meetings=meetings,
                won=won,
                reply_rate=round(row_replied / approvals * 100, 1) if approvals else 0,
            )
            for approval_type, subject, approvals, row_replied, meetings, won in rows
        ],
    )


@router.get(
    "/projects/{project_id}/saved-company-filters", response_model=list[SavedCompanyFilterOut]
)
def list_saved_company_filters(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    owned_project(project_id, db, user, write=False)
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
    owned_project(project_id, db, user, write=False)
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


@router.get("/projects/{project_id}/outreach-queue", response_model=list[OutreachQueueItemOut])
def outreach_queue(
    project_id: UUID,
    assignee: str | None = Query(None, max_length=200),
    due: Literal["overdue", "today", "upcoming", "unset"] | None = None,
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user, write=False)
    now = datetime.now(timezone.utc)
    query = select(Company).where(
        Company.project_id == project_id,
        Company.status.in_(("target", "approached", "replied", "meeting")),
        Company.do_not_contact.is_(False),
        or_(
            Company.email != "",
            Company.contact_url != "",
            Company.phone != "",
            Company.instagram_url != "",
            Company.x_url != "",
            Company.tiktok_url != "",
            Company.facebook_url != "",
            Company.line_url != "",
        ),
    )
    if assignee:
        query = query.where(Company.assignee.ilike(f"%{assignee}%"))
    if due == "overdue":
        query = query.where(Company.next_followup_at < now)
    elif due == "today":
        day_start = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(
            Company.next_followup_at >= now,
            Company.next_followup_at < day_start + timedelta(days=1),
        )
    elif due == "upcoming":
        query = query.where(Company.next_followup_at >= now)
    elif due == "unset":
        query = query.where(Company.next_followup_at.is_(None))
    priority = case(
        (Company.next_followup_at < now, 0),
        (Company.next_followup_at.is_not(None), 1),
        else_=2,
    )
    companies = db.scalars(
        query.order_by(
            priority,
            Company.next_followup_at.asc().nullslast(),
            Company.score.desc().nullslast(),
            Company.id,
        ).limit(limit)
    ).all()
    return [
        OutreachQueueItemOut(
            company=company,
            available_channels=channels,
            recommended_channel=channels[0],
            due_state=outreach_due_state(company, now),
        )
        for company in companies
        if (channels := outreach_channels(company))
    ]


@router.get("/projects/{project_id}/followup-tasks", response_model=list[FollowupTaskOut])
def list_followup_tasks(
    project_id: UUID,
    assignee: str | None = Query(None, max_length=200),
    due: Literal["overdue", "today", "upcoming"] | None = None,
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user, write=False)
    now = datetime.now(timezone.utc)
    query = select(Company).where(
        Company.project_id == project_id,
        Company.status.in_(("target", "approached", "replied", "meeting")),
        Company.do_not_contact.is_(False),
        Company.next_followup_at.is_not(None),
    )
    if assignee:
        query = query.where(Company.assignee.ilike(f"%{assignee}%"))
    if due == "overdue":
        query = query.where(Company.next_followup_at < now)
    elif due == "today":
        day_start = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(
            Company.next_followup_at >= now,
            Company.next_followup_at < day_start + timedelta(days=1),
        )
    elif due == "upcoming":
        query = query.where(Company.next_followup_at >= now)
    priority = case((Company.next_followup_at < now, 0), else_=1)
    companies = db.scalars(
        query.order_by(
            priority,
            Company.next_followup_at.asc(),
            Company.score.desc().nullslast(),
            Company.id,
        ).limit(limit)
    ).all()
    return [
        FollowupTaskOut(company=company, due_state=outreach_due_state(company, now))
        for company in companies
    ]


@router.get("/projects/{project_id}/reply-queue", response_model=list[ReplyQueueItemOut])
def list_reply_queue(
    project_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user, write=False)
    rows = db.execute(
        select(InboundEmail, Company)
        .join(Company, Company.id == InboundEmail.company_id)
        .where(
            Company.project_id == project_id,
            Company.status == "replied",
            Company.do_not_contact.is_(False),
            InboundEmail.classification == "reply",
            InboundEmail.handled_at.is_(None),
        )
        .order_by(InboundEmail.received_at.desc(), InboundEmail.id)
        .limit(limit * 5)
    ).all()
    items = []
    seen_company_ids = set()
    for inbound, company in rows:
        if company.id in seen_company_ids:
            continue
        seen_company_ids.add(company.id)
        items.append(
            ReplyQueueItemOut(
                company=company,
                inbound_email_id=inbound.id,
                sender_email=inbound.sender_email,
                subject=inbound.subject,
                preview=inbound.preview,
                received_at=inbound.received_at,
            )
        )
        if len(items) == limit:
            break
    return items


@router.post("/companies/{company_id}/followup-task", response_model=CompanyOut)
def resolve_followup_task(
    company_id: UUID,
    body: FollowupTaskResolveInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    if (
        company.status not in {"target", "approached", "replied", "meeting"}
        or company.do_not_contact
    ):
        raise HTTPException(409, "この企業の追客タスクは処理できません。")
    if company.next_followup_at is None:
        raise HTTPException(409, "処理する追客タスクがありません。")
    previous_due = company.next_followup_at
    if body.action == "rescheduled":
        if body.next_followup_at is None or body.next_followup_at <= datetime.now(timezone.utc):
            raise HTTPException(422, "延期する次回対応日時は現在より後にしてください。")
        company.next_followup_at = body.next_followup_at
        activity_note = (
            f"追客タスクを延期: {previous_due.isoformat()} から "
            f"{body.next_followup_at.isoformat()}（{body.note}）"
        )
    else:
        company.next_followup_at = None
        activity_note = f"追客タスクを完了: 期限 {previous_due.isoformat()}（{body.note}）"
    db.add(Activity(company_id=company.id, activity_type="note", note=activity_note))
    db.commit()
    db.refresh(company)
    return company


@router.post("/companies/{company_id}/reply-response", response_model=CompanyOut)
def record_reply_response(
    company_id: UUID,
    body: ReplyResponseInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    if company.status != "replied" or company.do_not_contact:
        raise HTTPException(409, "この企業の返信対応は記録できません。")
    inbound = db.get(InboundEmail, body.inbound_email_id)
    if (
        inbound is None
        or inbound.company_id != company.id
        or inbound.classification != "reply"
    ):
        raise HTTPException(422, "この企業に紐付いた受信返信を指定してください。")
    if inbound.handled_at is not None:
        raise HTTPException(409, "この受信返信はすでに対応済みです。")
    activity_type = "meeting" if body.outcome == "meeting" else "email"
    if company.status != body.outcome:
        db.add(
            Activity(
                company_id=company.id,
                activity_type="status_change",
                note=f"営業状況を {company.status} から {body.outcome} に変更（返信対応）",
            )
        )
    db.add(Activity(company_id=company.id, activity_type=activity_type, note=body.note))
    if body.outcome in {"meeting", "won"} and inbound.outreach_approval_id:
        approval = db.get(OutreachDraftApproval, inbound.outreach_approval_id)
        if approval:
            record_outreach_conversion(
                db, approval, company, body.outcome, inbound_email=inbound
            )
    company.status = body.outcome
    company.next_followup_at = body.next_followup_at
    db.execute(
        update(InboundEmail)
        .where(
            InboundEmail.company_id == company.id,
            InboundEmail.classification == "reply",
            InboundEmail.handled_at.is_(None),
            InboundEmail.received_at <= inbound.received_at,
        )
        .values(handled_at=datetime.now(timezone.utc), handled_by_user_id=user.id)
    )
    db.commit()
    db.refresh(company)
    return company


@router.post("/companies/{company_id}/outreach", response_model=CompanyOut)
def record_outreach(
    company_id: UUID,
    body: OutreachRecordInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    if company.do_not_contact:
        raise HTTPException(409, "連絡禁止企業にはアプローチを記録できません。")
    if body.channel not in outreach_channels(company):
        raise HTTPException(409, "指定した連絡経路の情報がありません。")
    if company.status in {"won", "lost", "excluded"}:
        raise HTTPException(409, "完了済みの企業にはアプローチを記録できません。")
    if company.status != body.outcome:
        db.add(
            Activity(
                company_id=company.id,
                activity_type="status_change",
                note=f"営業状況を {company.status} から {body.outcome} に変更",
            )
        )
    db.add(Activity(company_id=company.id, activity_type=body.channel, note=body.note))
    company.status = body.outcome
    company.next_followup_at = body.next_followup_at
    db.commit()
    db.refresh(company)
    return company


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
    source: Literal["serper", "google_places", "gbizinfo", "url", "csv"] | None = None,
    keyword: str | None = Query(None, max_length=200),
    assignee: str | None = Query(None, max_length=200),
    followup: Literal["overdue", "today", "upcoming", "unset"] | None = None,
    sort: Literal["score_desc", "newest", "company_name"] = "score_desc",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user, write=False)
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
    return owned_company(company_id, db, user, write=False)


@router.patch("/companies/{company_id}/sales", response_model=CompanyOut)
def update_company_sales(
    company_id: UUID,
    body: CompanySalesInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    if company.do_not_contact and body.status != "excluded":
        raise HTTPException(409, "連絡禁止を解除してから営業状況を変更してください。")
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


@router.patch("/companies/{company_id}/contact-control", response_model=CompanyOut)
def update_contact_control(
    company_id: UUID,
    body: CompanyContactControlInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    match = or_(
        (SuppressionEntry.domain != "") & (SuppressionEntry.domain == company.domain),
        (SuppressionEntry.email != "")
        & (func.lower(SuppressionEntry.email) == company.email.lower()),
        (SuppressionEntry.phone != "") & (SuppressionEntry.phone == company.phone),
    )
    entries = db.scalars(
        select(SuppressionEntry).where(SuppressionEntry.project_id == company.project_id, match)
    ).all()
    if body.do_not_contact:
        if entries:
            for entry in entries:
                entry.reason = body.exclusion_reason
        else:
            db.add(
                SuppressionEntry(
                    project_id=company.project_id,
                    domain=company.domain or "",
                    email=company.email.lower(),
                    phone=company.phone,
                    reason=body.exclusion_reason,
                )
            )
        company.status = "excluded"
    else:
        for entry in entries:
            db.delete(entry)
    company.do_not_contact = body.do_not_contact
    company.exclusion_reason = body.exclusion_reason
    company.contact_quality_status = body.contact_quality_status
    company.contact_checked_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            company_id=company.id,
            activity_type="note",
            note=(
                f"連絡禁止に設定: {body.exclusion_reason}"
                if body.do_not_contact
                else f"連絡禁止を解除・連絡先品質を{body.contact_quality_status}に更新"
            ),
        )
    )
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
    if body.status != "excluded" and any(company.do_not_contact for company in companies):
        raise HTTPException(409, "連絡禁止企業が含まれています。")
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
    owned_company(company_id, db, user, write=False)
    return db.scalars(
        select(Activity)
        .where(Activity.company_id == company_id)
        .order_by(Activity.created_at.desc(), Activity.id)
        .limit(100)
    ).all()


@router.get("/companies/{company_id}/contacts", response_model=list[ContactPersonOut])
def list_contact_people(
    company_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_company(company_id, db, user, write=False)
    return db.scalars(
        select(ContactPerson)
        .where(ContactPerson.company_id == company_id)
        .order_by(ContactPerson.name, ContactPerson.created_at, ContactPerson.id)
    ).all()


@router.post("/companies/{company_id}/contacts", response_model=ContactPersonOut, status_code=201)
def create_contact_person(
    company_id: UUID,
    body: ContactPersonInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    values = body.model_dump()
    contact = ContactPerson(
        company_id=company.id,
        **values,
        verified_at=(
            datetime.now(timezone.utc) if body.verification_status == "verified" else None
        ),
    )
    db.add(contact)
    db.add(
        Activity(
            company_id=company.id,
            activity_type="note",
            note=f"先方担当者を追加: {body.name}",
        )
    )
    db.commit()
    db.refresh(contact)
    return contact


@router.put("/contacts/{contact_id}", response_model=ContactPersonOut)
def update_contact_person(
    contact_id: UUID,
    body: ContactPersonInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    contact = owned_contact_person(contact_id, db, user)
    was_verified = contact.verification_status == "verified"
    for key, value in body.model_dump().items():
        setattr(contact, key, value)
    if body.verification_status == "verified" and not was_verified:
        contact.verified_at = datetime.now(timezone.utc)
    elif body.verification_status != "verified":
        contact.verified_at = None
    db.add(
        Activity(
            company_id=contact.company_id,
            activity_type="note",
            note=f"先方担当者を更新: {body.name}",
        )
    )
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact_person(
    contact_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    contact = owned_contact_person(contact_id, db, user)
    db.add(
        Activity(
            company_id=contact.company_id,
            activity_type="note",
            note=f"先方担当者を削除: {contact.name}",
        )
    )
    db.delete(contact)
    db.commit()


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
    owned_project(project_id, db, user, write=False)
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
    owned_ids = select(Project.id).where(accessible_project_condition(user.id))
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
        .where(accessible_project_condition(user.id))
        .order_by(CollectionJob.created_at.desc(), CollectionJob.id)
        .limit(5)
    ).all()
    operation_rows = db.execute(
        select(OperationJob.status, func.count())
        .join(Project, Project.id == OperationJob.project_id)
        .where(accessible_project_condition(user.id))
        .group_by(OperationJob.status)
    ).all()
    unread_failures = db.scalar(
        select(func.count())
        .select_from(OperationJob)
        .join(Project, Project.id == OperationJob.project_id)
        .where(
            accessible_project_condition(user.id),
            OperationJob.status == "failed",
            OperationJob.acknowledged_at.is_(None),
        )
    )
    operations = db.scalars(
        select(OperationJob)
        .join(Project, Project.id == OperationJob.project_id)
        .where(accessible_project_condition(user.id))
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
