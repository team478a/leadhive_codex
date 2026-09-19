import csv
import io
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.analysis_routes import owned_company, owned_project
from app.database import get_db
from app.models import CollectionJob, Company, Project, User
from app.schemas import CompanyOut, CompanySalesInput, DashboardOut
from app.security import current_user

router = APIRouter(prefix="/api")


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


@router.get("/projects/{project_id}/company-list", response_model=list[CompanyOut])
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
    return db.scalars(query.offset(offset).limit(limit)).all()


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
    company.status = body.status
    company.notes = body.notes
    db.commit()
    db.refresh(company)
    return company


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
    return DashboardOut(
        total_companies=total or 0,
        ranks={key: count for key, count in rank_rows},
        statuses={key: count for key, count in status_rows},
        recent_jobs=jobs,
    )
