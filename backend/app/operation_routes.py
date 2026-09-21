from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AnalysisRefreshSchedule,
    CollectionJob,
    OperationJob,
    SearchSchedule,
    User,
)
from app.project_access import project_access
from app.schemas import (
    AnalysisRefreshScheduleInput,
    AnalysisRefreshScheduleOut,
    CollectionPerformanceOut,
    OperationJobInput,
    OperationJobOut,
    SearchAnalyticsOut,
    SearchScheduleInput,
    SearchScheduleOut,
)
from app.security import current_user
from app.services.operations import refresh_company_ids

router = APIRouter(prefix="/api")


def owned_operation(job_id: UUID, db: Session, user: User) -> OperationJob:
    job = db.get(OperationJob, job_id)
    if job is None:
        raise HTTPException(404, "処理ジョブが見つかりません。")
    project_access(job.project_id, db, user)
    return job


def owned_schedule(schedule_id: UUID, db: Session, user: User) -> SearchSchedule:
    schedule = db.get(SearchSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "定期収集が見つかりません。")
    project_access(schedule.project_id, db, user)
    return schedule


@router.get(
    "/projects/{project_id}/analysis-refresh-schedule",
    response_model=AnalysisRefreshScheduleOut | None,
)
def get_analysis_refresh_schedule(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    return db.scalar(
        select(AnalysisRefreshSchedule).where(AnalysisRefreshSchedule.project_id == project_id)
    )


@router.put(
    "/projects/{project_id}/analysis-refresh-schedule",
    response_model=AnalysisRefreshScheduleOut,
)
def upsert_analysis_refresh_schedule(
    project_id: UUID,
    body: AnalysisRefreshScheduleInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    schedule = db.scalar(
        select(AnalysisRefreshSchedule).where(AnalysisRefreshSchedule.project_id == project_id)
    )
    if schedule is None:
        schedule = AnalysisRefreshSchedule(project_id=project_id, **body.model_dump())
        db.add(schedule)
    else:
        for key, value in body.model_dump().items():
            setattr(schedule, key, value)
    schedule.next_run_at = datetime.now(timezone.utc) + timedelta(hours=body.interval_hours)
    schedule.last_error = ""
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/projects/{project_id}/analysis-refresh-schedule", status_code=204)
def delete_analysis_refresh_schedule(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user)
    schedule = db.scalar(
        select(AnalysisRefreshSchedule).where(AnalysisRefreshSchedule.project_id == project_id)
    )
    if schedule is None:
        raise HTTPException(404, "自動再解析設定が見つかりません。")
    db.delete(schedule)
    db.commit()


@router.post(
    "/projects/{project_id}/analysis-refresh-schedule/run",
    response_model=OperationJobOut,
    status_code=202,
)
def run_analysis_refresh_schedule(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user)
    schedule = db.scalar(
        select(AnalysisRefreshSchedule).where(AnalysisRefreshSchedule.project_id == project_id)
    )
    if schedule is None:
        raise HTTPException(404, "自動再解析設定が見つかりません。")
    if db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "web_analysis",
            OperationJob.status.in_(("queued", "running")),
        )
    ):
        raise HTTPException(409, "Web解析がすでに実行待ちです。")
    company_ids = refresh_company_ids(db, schedule)
    if not company_ids:
        raise HTTPException(409, "再解析対象の企業はありません。")
    job = OperationJob(
        project_id=project_id,
        operation_type="web_analysis",
        payload={"company_ids": [str(item) for item in company_ids], "force": True},
    )
    now = datetime.now(timezone.utc)
    schedule.last_enqueued_at = now
    schedule.next_run_at = now + timedelta(hours=schedule.interval_hours)
    schedule.last_error = ""
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/projects/{project_id}/search-schedules", response_model=list[SearchScheduleOut])
def list_search_schedules(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    return db.scalars(
        select(SearchSchedule)
        .where(SearchSchedule.project_id == project_id)
        .order_by(SearchSchedule.created_at.desc())
    ).all()


@router.get("/projects/{project_id}/search-analytics", response_model=list[SearchAnalyticsOut])
def search_analytics(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    rows = db.execute(
        select(
            SearchSchedule.id,
            SearchSchedule.name,
            func.count(CollectionJob.id),
            func.coalesce(func.sum(CollectionJob.found_count), 0),
            func.coalesce(func.sum(CollectionJob.saved_count), 0),
            func.coalesce(func.sum(CollectionJob.duplicate_count), 0),
            func.coalesce(func.sum(CollectionJob.excluded_count), 0),
            func.coalesce(func.sum(CollectionJob.error_count), 0),
        )
        .outerjoin(CollectionJob, CollectionJob.search_schedule_id == SearchSchedule.id)
        .where(SearchSchedule.project_id == project_id)
        .group_by(SearchSchedule.id, SearchSchedule.name)
        .order_by(func.coalesce(func.sum(CollectionJob.saved_count), 0).desc(), SearchSchedule.name)
    ).all()
    return [
        SearchAnalyticsOut(
            schedule_id=schedule_id,
            name=name,
            run_count=run_count,
            found_count=found,
            saved_count=saved,
            duplicate_count=duplicates,
            excluded_count=excluded,
            error_count=errors,
            save_rate=round(saved / found * 100, 1) if found else 0,
            duplicate_rate=round(duplicates / found * 100, 1) if found else 0,
        )
        for schedule_id, name, run_count, found, saved, duplicates, excluded, errors in rows
    ]


@router.get(
    "/projects/{project_id}/collection-performance", response_model=list[CollectionPerformanceOut]
)
def collection_performance(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Compare real collection outcomes by source and search keyword."""
    project_access(project_id, db, user, write=False)
    rows = db.execute(
        select(
            CollectionJob.source,
            CollectionJob.keyword,
            func.count(CollectionJob.id),
            func.coalesce(func.sum(CollectionJob.found_count), 0),
            func.coalesce(func.sum(CollectionJob.saved_count), 0),
            func.coalesce(func.sum(CollectionJob.duplicate_count), 0),
            func.coalesce(func.sum(CollectionJob.excluded_count), 0),
            func.coalesce(func.sum(CollectionJob.error_count), 0),
            func.coalesce(func.avg(func.nullif(CollectionJob.processing_ms, 0)), 0),
        )
        .where(CollectionJob.project_id == project_id)
        .group_by(CollectionJob.source, CollectionJob.keyword)
        .order_by(
            func.coalesce(func.sum(CollectionJob.saved_count), 0).desc(),
            CollectionJob.source,
            CollectionJob.keyword,
        )
    ).all()
    return [
        CollectionPerformanceOut(
            source=source,
            keyword=keyword,
            run_count=run_count,
            found_count=found,
            saved_count=saved,
            duplicate_count=duplicates,
            excluded_count=excluded,
            error_count=errors,
            save_rate=round(saved / found * 100, 1) if found else 0,
            excluded_rate=round(excluded / found * 100, 1) if found else 0,
            average_processing_ms=round(float(average_processing_ms or 0)),
        )
        for (
            source,
            keyword,
            run_count,
            found,
            saved,
            duplicates,
            excluded,
            errors,
            average_processing_ms,
        ) in rows
    ]


@router.post(
    "/projects/{project_id}/search-schedules", response_model=SearchScheduleOut, status_code=201
)
def create_search_schedule(
    project_id: UUID,
    body: SearchScheduleInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    schedule = SearchSchedule(
        project_id=project_id,
        **body.model_dump(),
        next_run_at=datetime.now(timezone.utc) + timedelta(hours=body.interval_hours),
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.put("/search-schedules/{schedule_id}", response_model=SearchScheduleOut)
def update_search_schedule(
    schedule_id: UUID,
    body: SearchScheduleInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    schedule = owned_schedule(schedule_id, db, user)
    for key, value in body.model_dump().items():
        setattr(schedule, key, value)
    schedule.next_run_at = datetime.now(timezone.utc) + timedelta(hours=body.interval_hours)
    schedule.last_error = ""
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/search-schedules/{schedule_id}", status_code=204)
def delete_search_schedule(
    schedule_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    db.delete(owned_schedule(schedule_id, db, user))
    db.commit()


@router.post("/search-schedules/{schedule_id}/run", response_model=OperationJobOut, status_code=202)
def run_search_schedule(
    schedule_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    schedule = owned_schedule(schedule_id, db, user)
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == schedule.project_id,
            OperationJob.operation_type == "collect_search",
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        raise HTTPException(409, "検索収集がすでに実行待ちです。")
    job = OperationJob(
        project_id=schedule.project_id,
        operation_type="collect_search",
        payload={
            "source": schedule.source,
            "keywords": schedule.keywords,
            "region": schedule.region,
            "max_results": schedule.max_results,
            "company_limit": schedule.company_limit,
            "schedule_id": str(schedule.id),
        },
    )
    schedule.last_enqueued_at = datetime.now(timezone.utc)
    schedule.next_run_at = schedule.last_enqueued_at + timedelta(hours=schedule.interval_hours)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/projects/{project_id}/operations", response_model=OperationJobOut, status_code=202)
def enqueue_operation(
    project_id: UUID,
    body: OperationJobInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == body.operation_type,
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        raise HTTPException(409, "同じ種類の処理がすでに実行待ちです。")
    payload = body.model_dump(mode="json", exclude={"operation_type"})
    job = OperationJob(project_id=project_id, operation_type=body.operation_type, payload=payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/projects/{project_id}/operations", response_model=list[OperationJobOut])
def list_operations(
    project_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    return db.scalars(
        select(OperationJob)
        .where(OperationJob.project_id == project_id)
        .order_by(OperationJob.created_at.desc(), OperationJob.id)
        .limit(limit)
    ).all()


@router.post("/operations/{job_id}/cancel", response_model=OperationJobOut)
def cancel_operation(
    job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    job = owned_operation(job_id, db, user)
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
    elif job.status == "running":
        job.cancel_requested = True
    db.commit()
    db.refresh(job)
    return job


@router.post("/operations/{job_id}/retry", response_model=OperationJobOut, status_code=202)
def retry_operation(
    job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    source = owned_operation(job_id, db, user)
    if source.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "失敗またはキャンセル済みのジョブだけ再実行できます。")
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == source.project_id,
            OperationJob.operation_type == source.operation_type,
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        raise HTTPException(409, "同じ種類の処理がすでに実行待ちです。")
    job = OperationJob(
        project_id=source.project_id,
        operation_type=source.operation_type,
        payload=source.payload,
    )
    source.acknowledged_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/operations/{job_id}/acknowledge", response_model=OperationJobOut)
def acknowledge_operation(
    job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    job = owned_operation(job_id, db, user)
    if job.status != "failed":
        raise HTTPException(409, "失敗したジョブだけ確認済みにできます。")
    if job.acknowledged_at is None:
        job.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
    return job
