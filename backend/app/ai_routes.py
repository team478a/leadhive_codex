import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_routes import owned_company, owned_project
from app.config import settings
from app.database import get_db
from app.models import Company, Project, TargetProfile, User
from app.schemas import AiAnalysisInput, CompanyAiAnalysisInput, CompanyOut
from app.security import current_user
from app.services.ai import AiAnalysisError, AnalysisContext, get_ai_provider, rank_for_score

logger = logging.getLogger("leadhive")
router = APIRouter(prefix="/api")


def context_for(company: Company, project: Project, profile: TargetProfile) -> AnalysisContext:
    return AnalysisContext(
        company_name=company.company_name,
        website_url=company.website_url or "",
        address=company.address,
        business_summary=company.business_summary,
        website_text=company.website_text[: settings.ai_max_website_chars],
        sns_urls={
            "instagram": company.instagram_url,
            "x": company.x_url,
            "tiktok": company.tiktok_url,
            "facebook": company.facebook_url,
            "youtube": company.youtube_url,
            "line": company.line_url,
        },
        contact_available=bool(company.contact_url or company.email or company.phone),
        profile_name=profile.profile_name,
        profile_description=profile.description,
        positive_keywords=profile.positive_keywords,
        negative_keywords=profile.negative_keywords,
        exclusion_keywords=profile.exclusion_keywords,
        scoring_rules=profile.scoring_rules,
        ai_instruction=profile.ai_instruction,
        sales_objective=project.sales_objective,
        region=project.region,
    )


def analyze_company_ai(
    db: Session, company: Company, project: Project, profile: TargetProfile, force: bool = False
) -> Company:
    if company.ai_status == "completed" and not force:
        return company
    if company.analysis_status in {"duplicate", "excluded"}:
        company.ai_status = "skipped"
        company.ai_error = "重複または対象外の企業はAI判定しません。"
        company.ai_analyzed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        return company
    if not (company.website_text or company.business_summary):
        company.ai_status = "skipped"
        company.ai_error = "先にWeb解析を完了してください。"
        company.ai_analyzed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        return company

    company.ai_status = "running"
    company.ai_error = ""
    db.commit()
    logger.info("AI analysis start: company_id=%s", company.id)
    try:
        provider = get_ai_provider()
        result = provider.analyze(context_for(company, project, profile))
        rank = rank_for_score(result.score, profile.scoring_rules)
        company.score = result.score
        company.rank = rank
        company.is_target = rank != "対象外"
        company.business_type = result.business_type[:300]
        company.ai_summary = result.summary
        company.ai_reason = result.reason
        company.ai_strengths = result.strengths
        company.ai_concerns = result.concerns
        company.ai_recommended_approach = result.recommended_approach
        company.ai_status = "completed"
        company.ai_error = ""
        company.ai_provider = provider.name
        company.ai_model = provider.model
        company.ai_analyzed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        logger.info("AI analysis end: company_id=%s status=completed", company.id)
        return company
    except AiAnalysisError as exc:
        db.rollback()
        company = db.get(Company, company.id)
        company.ai_status = "failed"
        company.ai_error = exc.public_message[:500]
        company.ai_analyzed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        logger.warning("AI error: company_id=%s type=%s", company.id, type(exc).__name__)
        return company
    except Exception as exc:
        db.rollback()
        company = db.get(Company, company.id)
        company.ai_status = "failed"
        company.ai_error = "AI判定中にエラーが発生しました。"
        company.ai_analyzed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        logger.error("AI error: company_id=%s type=%s", company.id, type(exc).__name__)
        return company


def project_and_profile(db: Session, project_id: UUID, user: User) -> tuple[Project, TargetProfile]:
    project = owned_project(project_id, db, user)
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
    company = owned_company(company_id, db, user)
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
    elif not body.force:
        query = query.where(
            Company.analysis_status == "completed",
            Company.ai_status.in_(("pending", "failed", "skipped")),
        )
    companies = db.scalars(query.order_by(Company.created_at, Company.id).limit(body.limit)).all()
    if body.company_ids and len(companies) != len(set(body.company_ids)):
        raise HTTPException(404, "指定された企業が見つかりません。")
    return [analyze_company_ai(db, company, project, profile, body.force) for company in companies]
