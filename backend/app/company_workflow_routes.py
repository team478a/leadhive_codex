from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, or_, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Activity, Company, InboundEmail, OutreachDraftApproval, User
from app.project_access import company_access as owned_company
from app.project_access import project_access as owned_project
from app.schemas import (
    ActivityInput,
    ActivityOut,
    CompanyBulkSalesInput,
    CompanyOut,
    CompanySalesInput,
    FollowupTaskOut,
    FollowupTaskResolveInput,
    OutreachQueueItemOut,
    OutreachRecordInput,
    ReplyQueueItemOut,
    ReplyResponseInput,
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
    if inbound is None or inbound.company_id != company.id or inbound.classification != "reply":
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
            record_outreach_conversion(db, approval, company, body.outcome, inbound_email=inbound)
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
