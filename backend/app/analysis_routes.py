import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, Project, User
from app.schemas import CompanyAnalysisInput, CompanyOut, WebAnalysisInput
from app.security import current_user
from app.services.collection import canonicalize_url
from app.services.scraper import ScrapeError, is_aggregator_domain, scrape_company

logger = logging.getLogger("leadhive")
router = APIRouter(prefix="/api")
PROTECTABLE_WEB_FIELDS = (
    "company_name",
    "address",
    "prefecture",
    "city",
    "phone",
    "email",
    "contact_url",
    "instagram_url",
    "x_url",
    "tiktok_url",
    "facebook_url",
    "youtube_url",
    "line_url",
)


def update_unprotected_fields(company: Company, data) -> None:
    protected = set(company.protected_fields or [])
    for field in PROTECTABLE_WEB_FIELDS:
        value = getattr(data, field)
        if field not in protected and value:
            setattr(company, field, value)


def owned_project(project_id: UUID, db: Session, user: User) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise HTTPException(404, "プロジェクトが見つかりません。")
    return project


def owned_company(company_id: UUID, db: Session, user: User) -> Company:
    company = db.scalar(
        select(Company)
        .join(Project, Project.id == Company.project_id)
        .where(Company.id == company_id, Project.user_id == user.id)
    )
    if company is None:
        raise HTTPException(404, "企業が見つかりません。")
    return company


def find_duplicate(
    db: Session,
    company: Company,
    website_url: str,
    domain: str,
    company_name: str,
    address: str,
) -> Company | None:
    conditions = [Company.domain == domain, Company.website_url == website_url]
    if company_name and address:
        conditions.append((Company.company_name == company_name) & (Company.address == address))
    return db.scalar(
        select(Company)
        .where(
            Company.project_id == company.project_id,
            Company.id != company.id,
            or_(*conditions),
        )
        .order_by(Company.created_at, Company.id)
        .limit(1)
    )


def analyze(db: Session, company: Company, force: bool = False) -> Company:
    if company.analysis_status == "completed" and not force:
        return company
    if not company.website_url:
        company.analysis_status = "skipped"
        company.analysis_error = "WebサイトURLが登録されていません。"
        company.scraped_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        return company
    if company.domain and is_aggregator_domain(company.domain):
        company.analysis_status = "excluded"
        company.analysis_error = "企業公式サイトではない可能性があるドメインです。"
        company.is_aggregator = True
        company.scraped_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        return company
    company.analysis_status = "running"
    company.analysis_error = ""
    db.commit()
    logger.info("scraper start: company_id=%s", company.id)
    try:
        page, data = scrape_company(company.website_url)
        website_url, domain = canonicalize_url(page.url)
        protected = set(company.protected_fields or [])
        name = (
            company.company_name
            if "company_name" in protected
            else (data.company_name or company.company_name)
        )
        address = company.address if "address" in protected else (data.address or company.address)
        duplicate = find_duplicate(db, company, website_url, domain, name, address)
        if duplicate:
            company.analysis_status = "duplicate"
            company.duplicate_of_id = duplicate.id
            company.analysis_error = "同一プロジェクト内に重複する企業があります。"
        else:
            company.website_url = website_url
            company.domain = domain
            update_unprotected_fields(company, data)
            company.business_summary = data.business_summary
            company.website_text = data.website_text
            company.contact_quality_status = (
                "observed" if company.phone or company.email or company.contact_url else "unknown"
            )
            company.contact_source_url = company.contact_url or page.url
            company.contact_checked_at = datetime.now(timezone.utc)
            company.analysis_status = "completed"
            company.analysis_error = ""
            company.duplicate_of_id = None
        company.scraped_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        logger.info("scraper end: company_id=%s status=%s", company.id, company.analysis_status)
        return company
    except ScrapeError as exc:
        db.rollback()
        company = db.get(Company, company.id)
        company.analysis_status = "failed"
        company.analysis_error = exc.public_message[:500]
        company.scraped_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        logger.warning("scraper error: company_id=%s type=%s", company.id, type(exc).__name__)
        return company
    except Exception as exc:
        db.rollback()
        company = db.get(Company, company.id)
        company.analysis_status = "failed"
        company.analysis_error = "Webサイト解析中にエラーが発生しました。"
        company.scraped_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(company)
        logger.error("scraper error: company_id=%s type=%s", company.id, type(exc).__name__)
        return company


@router.post("/companies/{company_id}/analyze", response_model=CompanyOut)
def analyze_company(
    company_id: UUID,
    body: CompanyAnalysisInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    return analyze(db, company, body.force)


@router.post("/projects/{project_id}/web-analysis", response_model=list[CompanyOut])
def analyze_project(
    project_id: UUID,
    body: WebAnalysisInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    query = select(Company).where(Company.project_id == project_id)
    if body.company_ids:
        query = query.where(Company.id.in_(body.company_ids))
    elif not body.force:
        query = query.where(Company.analysis_status.in_(("pending", "failed")))
    companies = db.scalars(query.order_by(Company.created_at, Company.id).limit(body.limit)).all()
    if body.company_ids and len(companies) != len(set(body.company_ids)):
        raise HTTPException(404, "指定された企業が見つかりません。")
    return [analyze(db, company, body.force) for company in companies]
