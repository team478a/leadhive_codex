from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, Project, TargetProfile, User
from app.project_access import company_access, project_access
from app.schemas import AiAnalysisInput, AiAnalysisTargetsOut, CompanyAiAnalysisInput, CompanyOut
from app.security import current_user
from app.services.ai_analysis import analyze_company_ai
from app.services.ai_targeting import ai_company_query, ai_target_count

router = APIRouter(prefix="/api")


def project_and_profile(db: Session, project_id: UUID, user: User) -> tuple[Project, TargetProfile]:
    project = project_access(project_id, db, user)
    profile = db.get(TargetProfile, project.target_profile_id)
    if profile is None:
        raise HTTPException(409, "プロジェクトのプロファイルが見つかりません。")
    return project, profile


@router.post("/companies/{company_id}/ai-analysis", response_model=CompanyOut)
def analyze_one(
    company_id: UUID,
    body: CompanyAiAnalysisInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = company_access(company_id, db, user)
    project, profile = project_and_profile(db, company.project_id, user)
    return analyze_company_ai(db, company, project, profile, body.force)


@router.post("/projects/{project_id}/ai-analysis", response_model=list[CompanyOut])
def analyze_many(
    project_id: UUID,
    body: AiAnalysisInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project, profile = project_and_profile(db, project_id, user)
    query = select(Company).where(Company.project_id == project_id)
    if body.company_ids:
        query = query.where(Company.id.in_(body.company_ids))
    else:
        query = ai_company_query(
            project_id,
            scope=body.target_scope,
            force=body.force,
        )
    companies = db.scalars(query.order_by(Company.created_at, Company.id).limit(body.limit)).all()
    if body.company_ids and len(companies) != len(set(body.company_ids)):
        raise HTTPException(404, "指定された企業が見つかりません。")
    return [analyze_company_ai(db, company, project, profile, body.force) for company in companies]


@router.get(
    "/projects/{project_id}/ai-analysis/targets",
    response_model=AiAnalysisTargetsOut,
)
def ai_analysis_targets(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    return AiAnalysisTargetsOut(
        eligible_count=ai_target_count(db, project_id, scope="eligible"),
        all_count=ai_target_count(db, project_id, scope="all"),
    )
