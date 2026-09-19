import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CollectionJob, Company, Project, User
from app.schemas import (
    CollectionJobOut,
    CompanyOut,
    SearchCollectionInput,
    UrlCollectionInput,
)
from app.security import current_user
from app.services.collection import (
    Candidate,
    ExternalServiceError,
    canonicalize_url,
    parse_csv,
    parse_urls,
    search_google_places,
    search_serper,
)

logger = logging.getLogger("leadhive")
router = APIRouter(prefix="/api")


def owned_project(project_id: UUID, db: Session, user: User) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise HTTPException(404, "プロジェクトが見つかりません。")
    return project


def owned_job(job_id: UUID, db: Session, user: User) -> CollectionJob:
    job = db.scalar(
        select(CollectionJob)
        .join(Project, Project.id == CollectionJob.project_id)
        .where(CollectionJob.id == job_id, Project.user_id == user.id)
    )
    if job is None:
        raise HTTPException(404, "収集ジョブが見つかりません。")
    return job


def start_job(
    db: Session,
    project_id: UUID,
    source: str,
    keyword: str,
    region: str,
    operation_job_id: UUID | None = None,
    search_schedule_id: UUID | None = None,
):
    job = CollectionJob(
        project_id=project_id,
        operation_job_id=operation_job_id,
        search_schedule_id=search_schedule_id,
        source=source,
        keyword=keyword,
        region=region,
        status="running",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info("collection job start: id=%s source=%s", job.id, source)
    return job


def is_duplicate(db: Session, project_id: UUID, candidate: Candidate) -> bool:
    conditions = []
    domain = None
    if candidate.website_url:
        _, domain = canonicalize_url(candidate.website_url)
        conditions.extend([Company.domain == domain, Company.website_url == candidate.website_url])
    if candidate.address:
        conditions.append(
            (Company.company_name == candidate.company_name)
            & (Company.address == candidate.address)
        )
    if not conditions:
        return False
    return (
        db.scalar(
            select(Company.id).where(Company.project_id == project_id, or_(*conditions)).limit(1)
        )
        is not None
    )


def save_candidates(
    db: Session,
    job: CollectionJob,
    candidates: list[Candidate],
    source_keyword: str = "",
    input_errors: int = 0,
):
    job.found_count = len(candidates) + input_errors
    job.error_count = input_errors
    for candidate in candidates:
        if is_duplicate(db, job.project_id, candidate):
            job.duplicate_count += 1
            continue
        domain = None
        if candidate.website_url:
            candidate.website_url, domain = canonicalize_url(candidate.website_url)
        company = Company(
            project_id=job.project_id,
            company_name=candidate.company_name,
            website_url=candidate.website_url,
            domain=domain,
            address=candidate.address,
            phone=candidate.phone,
            email=candidate.email,
            source=job.source,
            source_keyword=source_keyword,
        )
        try:
            with db.begin_nested():
                db.add(company)
                db.flush()
        except IntegrityError:
            job.duplicate_count += 1
        else:
            job.saved_count += 1
    job.status = "completed"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    logger.info(
        "collection job end: id=%s status=completed found=%s saved=%s duplicates=%s errors=%s",
        job.id,
        job.found_count,
        job.saved_count,
        job.duplicate_count,
        job.error_count,
    )
    return job


def fail_job(db: Session, job: CollectionJob, message: str):
    job.status = "failed"
    job.error_count = max(job.error_count, 1)
    job.error_message = message[:500]
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    logger.info("collection job end: id=%s status=failed", job.id)
    return job


@router.get("/projects/{project_id}/companies", response_model=list[CompanyOut])
def list_companies(
    project_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    return db.scalars(
        select(Company)
        .where(Company.project_id == project_id)
        .order_by(Company.created_at.desc(), Company.id)
        .offset(offset)
        .limit(limit)
    ).all()


@router.get("/projects/{project_id}/collection-jobs", response_model=list[CollectionJobOut])
def list_jobs(
    project_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    return db.scalars(
        select(CollectionJob)
        .where(CollectionJob.project_id == project_id)
        .order_by(CollectionJob.created_at.desc(), CollectionJob.id)
        .offset(offset)
        .limit(limit)
    ).all()


@router.get("/collection-jobs/{job_id}", response_model=CollectionJobOut)
def get_job(job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return owned_job(job_id, db, user)


@router.post(
    "/projects/{project_id}/collection-jobs/search",
    response_model=list[CollectionJobOut],
    status_code=201,
)
def collect_search(
    project_id: UUID,
    body: SearchCollectionInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    jobs = []
    for keyword in body.keywords:
        job = start_job(db, project_id, body.source, keyword, body.region)
        try:
            if body.source == "serper":
                candidates = search_serper(keyword, body.region, body.max_results)
            else:
                candidates = search_google_places(keyword, body.region, body.max_results)
            jobs.append(save_candidates(db, job, candidates, keyword))
        except ExternalServiceError as exc:
            jobs.append(fail_job(db, job, exc.public_message))
    return jobs


@router.post(
    "/projects/{project_id}/collection-jobs/urls",
    response_model=CollectionJobOut,
    status_code=201,
)
def collect_urls(
    project_id: UUID,
    body: UrlCollectionInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    job = start_job(db, project_id, "url", "", "")
    candidates, errors = parse_urls(body.urls)
    return save_candidates(db, job, candidates, input_errors=errors)


@router.post(
    "/projects/{project_id}/collection-jobs/csv",
    response_model=CollectionJobOut,
    status_code=201,
)
async def collect_csv(
    project_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(422, "CSVファイルを選択してください。")
    content = await file.read(5 * 1024 * 1024 + 1)
    try:
        candidates, errors = parse_csv(content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    job = start_job(db, project_id, "csv", file.filename[:500], "")
    return save_candidates(db, job, candidates, input_errors=errors)
