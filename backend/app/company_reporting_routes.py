"""Company reporting, saved-filter, and assignee analytics HTTP endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Activity,
    Company,
    OutreachConversion,
    OutreachDraft,
    OutreachDraftApproval,
    Project,
    SavedCompanyFilter,
    User,
)
from app.project_access import accessible_project_condition
from app.project_access import project_access as owned_project
from app.schemas import (
    AssigneeAnalyticsOut,
    OutreachEffectivenessAnalyticsOut,
    OutreachEffectivenessItemOut,
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
        .outerjoin(OutreachConversion, OutreachConversion.approval_id == OutreachDraftApproval.id)
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
