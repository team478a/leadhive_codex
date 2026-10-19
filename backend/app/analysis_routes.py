from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, User
from app.project_access import company_access, project_access
from app.schemas import CompanyAnalysisInput, OperationJobOut, WebAnalysisInput
from app.security import current_user
from app.services.site_analysis import enqueue_site_analysis

router = APIRouter(prefix="/api")


@router.post("/companies/{company_id}/analyze", response_model=OperationJobOut, status_code=202)
def analyze_company(
    company_id: UUID,
    body: CompanyAnalysisInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = company_access(company_id, db, user)
    job = enqueue_site_analysis(db, company.project_id, [company.id], force=body.force)
    if job is None:
        raise HTTPException(409, "サイト解析を登録できませんでした。")
    return OperationJobOut.model_validate(job)


@router.post(
    "/projects/{project_id}/web-analysis",
    response_model=OperationJobOut,
    status_code=202,
)
def analyze_project(
    project_id: UUID,
    body: WebAnalysisInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    query = select(Company).where(Company.project_id == project_id)
    if body.company_ids:
        query = query.where(Company.id.in_(body.company_ids))
    elif not body.force:
        query = query.where(Company.analysis_status.in_(("pending", "failed")))
    companies = db.scalars(query.order_by(Company.created_at, Company.id).limit(body.limit)).all()
    if body.company_ids and len(companies) != len(set(body.company_ids)):
        raise HTTPException(404, "指定された企業が見つかりません。")
    job = enqueue_site_analysis(
        db,
        project_id,
        [company.id for company in companies],
        force=body.force,
    )
    if job is None:
        raise HTTPException(409, "サイト解析の対象がありません。")
    return OperationJobOut.model_validate(job)
