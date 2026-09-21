import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Activity,
    CollectionJob,
    Company,
    ContactPerson,
    OperationJob,
    Project,
    SuppressionEntry,
    User,
)
from app.project_access import accessible_project_condition
from app.project_access import company_access as owned_company
from app.project_access import project_access as owned_project
from app.schemas import (
    CompanyBulkAssigneeInput,
    CompanyContactControlInput,
    CompanyEditInput,
    CompanyOut,
    CompanyPageOut,
    ContactPersonInput,
    ContactPersonOut,
    DashboardOut,
)
from app.security import current_user

router = APIRouter(prefix="/api")
JST = ZoneInfo("Asia/Tokyo")


def owned_contact_person(contact_id: UUID, db: Session, user: User) -> ContactPerson:
    contact = db.get(ContactPerson, contact_id)
    if contact is None:
        raise HTTPException(404, "担当者情報が見つかりません。")
    owned_company(contact.company_id, db, user)
    return contact


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
