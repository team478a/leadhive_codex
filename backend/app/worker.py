import argparse
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.ai_routes import analyze_company_ai
from app.analysis_routes import analyze
from app.collection_routes import fail_job, save_candidates, start_job
from app.database import SessionLocal
from app.models import Company, OperationJob, Project, TargetProfile
from app.services.collection import ExternalServiceError, search_google_places, search_serper

logger = logging.getLogger("leadhive")


def claim_job(db) -> OperationJob | None:
    job = db.scalar(
        select(OperationJob)
        .where(OperationJob.status == "queued")
        .order_by(OperationJob.created_at, OperationJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
    return job


def cancelled(db, job: OperationJob) -> bool:
    db.refresh(job)
    if job.cancel_requested:
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return True
    return False


def progress(db, job: OperationJob, success: bool) -> None:
    job.processed_count += 1
    job.success_count += int(success)
    job.failed_count += int(not success)
    db.commit()


def run_collection(db, job: OperationJob) -> None:
    payload = job.payload
    keywords = payload["keywords"]
    job.total_count = len(keywords)
    db.commit()
    for keyword in keywords:
        if cancelled(db, job):
            return
        collection = start_job(db, job.project_id, payload["source"], keyword, payload["region"])
        try:
            search = search_serper if payload["source"] == "serper" else search_google_places
            candidates = search(keyword, payload["region"], payload["max_results"])
            save_candidates(db, collection, candidates, keyword)
            progress(db, job, True)
        except ExternalServiceError as exc:
            fail_job(db, collection, exc.public_message)
            progress(db, job, False)


def selected_companies(db, job: OperationJob, ai: bool) -> list[Company]:
    payload = job.payload
    query = select(Company).where(Company.project_id == job.project_id)
    if payload.get("company_ids"):
        query = query.where(Company.id.in_(payload["company_ids"]))
    elif ai:
        query = query.where(Company.analysis_status == "completed")
        if not payload.get("force"):
            query = query.where(Company.ai_status.in_(("pending", "failed", "skipped")))
    elif not payload.get("force"):
        query = query.where(Company.analysis_status.in_(("pending", "failed")))
    return list(db.scalars(query.order_by(Company.created_at).limit(100)).all())


def run_web(db, job: OperationJob) -> None:
    companies = selected_companies(db, job, False)
    job.total_count = len(companies)
    db.commit()
    for company in companies:
        if cancelled(db, job):
            return
        result = analyze(db, company, job.payload.get("force", False))
        progress(db, job, result.analysis_status == "completed")


def run_ai(db, job: OperationJob) -> None:
    project = db.get(Project, job.project_id)
    profile = db.get(TargetProfile, project.target_profile_id)
    companies = selected_companies(db, job, True)
    job.total_count = len(companies)
    db.commit()
    for company in companies:
        if cancelled(db, job):
            return
        result = analyze_company_ai(db, company, project, profile, job.payload.get("force", False))
        progress(db, job, result.ai_status == "completed")


def run_once() -> bool:
    with SessionLocal() as db:
        job = claim_job(db)
        if job is None:
            return False
        logger.info("operation start: id=%s type=%s", job.id, job.operation_type)
        try:
            {"collect_search": run_collection, "web_analysis": run_web, "ai_analysis": run_ai}[
                job.operation_type
            ](db, job)
            db.refresh(job)
            if job.status == "running":
                job.status = "completed" if job.failed_count == 0 else "failed"
                job.error_message = "" if job.failed_count == 0 else "一部の処理に失敗しました。"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(OperationJob, job.id)
            job.status = "failed"
            job.error_message = "バックグラウンド処理に失敗しました。"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.error("operation error: id=%s type=%s", job.id, type(exc).__name__)
        logger.info("operation end: id=%s status=%s", job.id, job.status)
        return True


def main():
    parser = argparse.ArgumentParser(description="LeadHive background worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    while True:
        worked = run_once()
        if args.once:
            return
        if not worked:
            time.sleep(max(0.5, min(args.poll_seconds, 30)))


if __name__ == "__main__":
    main()
