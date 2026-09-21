"""Business logic for structured AI analysis of a company."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company, Project, TargetProfile
from app.services.ai import AiAnalysisError, AnalysisContext, get_ai_provider, rank_for_score

logger = logging.getLogger("leadhive")


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
