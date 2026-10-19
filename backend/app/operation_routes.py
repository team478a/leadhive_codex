from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    AnalysisRefreshSchedule,
    CollectionJob,
    Company,
    OperationJob,
    SearchSchedule,
    User,
)
from app.project_access import project_access
from app.schemas import (
    AnalysisRefreshScheduleInput,
    AnalysisRefreshScheduleOut,
    BrowserFormAnalysisInput,
    CollectionPerformanceOut,
    OperationJobInput,
    OperationJobOut,
    SearchAnalyticsOut,
    SearchScheduleInput,
    SearchScheduleOut,
)
from app.security import current_user
from app.services.browser_form_analysis import select_browser_analysis_targets
from app.services.operations import add_operation_job, refresh_company_ids

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
            OperationJob.operation_type.in_(("web_analysis", "site_analysis", "form_intelligence")),
            OperationJob.status.in_(("queued", "running")),
        )
    ):
        raise HTTPException(409, "Web解析がすでに実行待ちです。")
    company_ids = refresh_company_ids(db, schedule)
    if not company_ids:
        raise HTTPException(409, "再解析対象の企業はありません。")
    from app.services.site_analysis import enqueue_site_analysis

    job = enqueue_site_analysis(
        db,
        project_id,
        company_ids,
        force=True,
        expunge=False,
    )
    if job is None:
        raise HTTPException(409, "Web解析がすでに実行待ちです。")
    now = datetime.now(timezone.utc)
    schedule.last_enqueued_at = now
    schedule.next_run_at = now + timedelta(hours=schedule.interval_hours)
    schedule.last_error = ""
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
    if not add_operation_job(db, job):
        raise HTTPException(409, "検索収集がすでに実行待ちです。")
    schedule.last_enqueued_at = datetime.now(timezone.utc)
    schedule.next_run_at = schedule.last_enqueued_at + timedelta(hours=schedule.interval_hours)
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
    operation_type = (
        "site_analysis"
        if body.operation_type in {"web_analysis", "form_intelligence"}
        else body.operation_type
    )
    from app.preparation_routes import lock_project

    lock_project(db, project_id)
    if db.scalar(
        select(OperationJob.id)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "prepare_outreach",
            OperationJob.status.in_(("queued", "running")),
        )
        .limit(1)
    ):
        raise HTTPException(409, "営業準備が実行中です。完了または停止後に開始してください。")
    if operation_type == "site_analysis" and db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type.in_(("web_analysis", "form_intelligence")),
            OperationJob.status.in_(("queued", "running")),
        )
    ):
        raise HTTPException(409, "旧形式のサイト解析が実行中です。完了後に再試行してください。")
    if operation_type == "site_analysis":
        from app.services.site_analysis import (
            enqueue_site_analysis,
            enqueue_site_analysis_scan,
        )

        if body.company_ids:
            valid_ids = list(
                db.scalars(
                    select(Company.id).where(
                        Company.project_id == project_id,
                        Company.id.in_(body.company_ids),
                    )
                ).all()
            )
            if len(valid_ids) != len(set(body.company_ids)):
                raise HTTPException(404, "指定された企業が見つかりません。")
            job = enqueue_site_analysis(db, project_id, valid_ids, force=body.force, expunge=False)
        else:
            job = enqueue_site_analysis_scan(db, project_id, force=body.force)
        if job is None:
            raise HTTPException(409, "サイト解析ジョブを登録できませんでした。")
        return OperationJobOut.model_validate(job)
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == operation_type,
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        raise HTTPException(409, "同じ種類の処理がすでに実行待ちです。")
    if body.operation_type == "extract_articles":
        source_jobs = db.scalars(
            select(OperationJob).where(
                OperationJob.id.in_(body.source_operation_ids),
                OperationJob.project_id == project_id,
                OperationJob.operation_type == "collect_search",
            )
        ).all()
        if len(source_jobs) != len(set(body.source_operation_ids)):
            raise HTTPException(404, "指定された収集処理が見つかりません。")
    payload = body.model_dump(
        mode="json",
        exclude={
            "operation_type",
            "condition_request_id",
            "condition_version",
            "condition_hash",
            "collection_method",
            "form_first_query_types",
            "form_first_industry",
            "require_corporate_number",
        },
    )
    if body.collection_method == "form_first":
        from app.services.form_first_collection import build_form_first_queries

        query_plan = build_form_first_queries(
            [str(keyword) for keyword in body.keywords],
            body.form_first_query_types,
            body.form_first_industry,
        )
        payload.update(
            {
                "collection_method": "form_first",
                "form_first_query_types": body.form_first_query_types,
                "form_first_industry": body.form_first_industry,
                "form_first_query_order_version": "round-robin-v2",
                "form_first_industry_keywords": [str(keyword) for keyword in body.keywords],
                "form_first_query_map": {item["query"]: item for item in query_plan},
                "keywords": [item["query"] for item in query_plan],
                "target_count": body.target_count or 10000,
                "search_request_limit": None,
                "segment_request_limit": 20,
                "auto_continue": False,
                "require_corporate_number": body.require_corporate_number,
            }
        )
    if body.auto_continue:
        payload["collection_chain"] = {
            "root_ids": [],
            "total_requests": 0,
            "total_request_budget": body.search_request_limit or 50,
            "auto_continue": True,
            "continuation_count": 0,
        }
    if body.condition_request_id:
        from app.schema_collection_conditions import CollectionCondition
        from app.services.condition_collection import binding, merged_plan

        try:
            frozen = binding(
                db,
                project_id,
                body.condition_request_id,
                body.condition_version,
                body.condition_hash,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        conditions = [
            CollectionCondition.model_validate(c) for c in frozen["snapshot"]["conditions"]
        ]
        payload["condition_binding"] = frozen
        payload["presence_search"] = merged_plan(
            conditions, payload.get("presence_search")
        ).model_dump()
    job = OperationJob(project_id=project_id, operation_type=operation_type, payload=payload)
    if not add_operation_job(db, job):
        raise HTTPException(409, "同じ種類の処理がすでに実行待ちです。")
    from app.services.collection_query_plan import stamp_plan

    stamp_plan(job)
    db.commit()
    db.refresh(job)
    return job


@router.post(
    "/projects/{project_id}/browser-form-analysis",
    response_model=OperationJobOut,
    status_code=202,
)
def enqueue_synthetic_browser_form_analysis(
    project_id: UUID,
    body: BrowserFormAnalysisInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Queue only packaged synthetic fixtures; this endpoint deliberately has no URL field."""
    project_access(project_id, db, user)
    job = OperationJob(
        project_id=project_id,
        operation_type="browser_form_analysis",
        payload=body.model_dump(mode="json"),
        total_count=1,
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "同じ種類の処理がすでに実行待ちです。")
    db.commit()
    db.refresh(job)
    return job


@router.post(
    "/projects/{project_id}/browser-form-analysis/recalculate",
    response_model=OperationJobOut,
    status_code=202,
)
def enqueue_rendered_browser_form_analysis(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Queue at most 100 previously identified same-site contact pages, read-only."""
    project_access(project_id, db, user)
    if not settings.browser_form_analysis_enabled:
        raise HTTPException(
            409,
            "実サイトのブラウザ解析は既定で無効です。田中さんの承認後に管理者が有効化してください。",
        )
    active = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "browser_form_analysis",
            OperationJob.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if active:
        raise HTTPException(409, "ブラウザ解析ジョブがすでに実行中です。")
    targets = select_browser_analysis_targets(db, project_id)
    if not targets:
        raise HTTPException(409, "安全条件に合う未解析の問い合わせページがありません。")
    payload = {
        "mode": "rendered_analysis",
        "targets": [
            {
                "company_id": str(target.company_id),
                "profile_id": str(target.profile_id),
                "url": target.url,
                "site_host": target.site_host,
                "form_index": target.form_index,
            }
            for target in targets
        ],
    }
    job = OperationJob(
        project_id=project_id,
        operation_type="browser_form_analysis",
        payload=payload,
        total_count=len(targets),
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "ブラウザ解析ジョブを開始できませんでした。")
    db.commit()
    db.refresh(job)
    return OperationJobOut.model_validate(job)


@router.get("/collection-jobs/{job_id}/article-extractions")
def list_article_extractions(
    job_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    from app.model_article_extraction import CollectionArticleExtraction, CollectionExtractedEntry
    from app.model_collection_discovery import CollectionDiscoveryHit

    collection = db.get(CollectionJob, job_id)
    if collection is None:
        raise HTTPException(404, "収集ジョブが見つかりません。")
    project_access(collection.project_id, db, user, write=False)
    rows = db.scalars(
        select(CollectionArticleExtraction)
        .join(
            CollectionDiscoveryHit,
            CollectionDiscoveryHit.id == CollectionArticleExtraction.discovery_hit_id,
        )
        .where(CollectionDiscoveryHit.collection_job_id == job_id)
        .order_by(CollectionArticleExtraction.fetched_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": row.id,
                "article_url": row.article_url,
                "final_url": row.final_url,
                "status": row.status,
                "page_kind": row.page_kind,
                "pattern": row.pattern,
                "entry_count": row.entry_count,
                "linked_count": row.linked_count,
                "name_only_count": row.name_only_count,
                "rejected_count": row.rejected_count,
                "warnings": row.warnings,
                "entries": [
                    {
                        "id": entry.id,
                        "entry_order": entry.entry_order,
                        "name": entry.name,
                        "link_url": entry.link_url,
                        "status": entry.status,
                        "reasons": entry.reasons,
                        "disposition": entry.disposition,
                        "company_id": entry.company_id,
                    }
                    for entry in db.scalars(
                        select(CollectionExtractedEntry)
                        .where(CollectionExtractedEntry.extraction_id == row.id)
                        .order_by(CollectionExtractedEntry.entry_order)
                    ).all()
                ],
            }
            for row in rows
        ],
    }


@router.post("/operations/{job_id}/continue", response_model=OperationJobOut, status_code=202)
def continue_collection(
    job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    source = owned_operation(job_id, db, user)
    if source.status != "completed" or source.operation_type != "collect_search":
        raise HTTPException(409, "完了した検索収集だけ続きから再開できます。")
    progress = (source.payload or {}).get("collection_progress") or {}
    can_continue = progress.get("stop_reason") == "REQUEST_BUDGET_REACHED" and progress.get(
        "pending_queries"
    )
    if not can_continue:
        raise HTTPException(409, "続きから収集できる未検索項目がありません。")
    from app.services.collection_continuation import enqueue_continuation

    job = enqueue_continuation(db, source, automatic=False)
    if job is None:
        raise HTTPException(
            409, "続きの収集を登録できません。実行中の収集がないか確認してください。"
        )
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


@router.get("/operations/{job_id}/collection-conditions")
def condition_results(
    job_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    job = db.get(OperationJob, job_id)
    if job is None:
        raise HTTPException(404, "処理ジョブが見つかりません。")
    project_access(job.project_id, db, user, write=False)
    from app.services.condition_collection import operation_results

    try:
        return operation_results(db, job, offset, limit)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/operations/{job_id}/cancel", response_model=OperationJobOut)
def cancel_operation(
    job_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    job = owned_operation(job_id, db, user)
    if job.operation_type == "cf7_observation":
        from app.services import form_observation_jobs

        job = form_observation_jobs.owned_job(db, job_id, user)
        form_observation_jobs.cancel(db, job, user)
        db.commit()
        db.refresh(job)
        return job
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
    if source.operation_type == "cf7_observation":
        raise HTTPException(409, "静的フォーム観察は検証専用です。再実行はできません。")
    if source.operation_type == "prepare_outreach":
        raise HTTPException(409, "営業準備専用の再開操作を使用してください。")
    if source.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "失敗またはキャンセル済みのジョブだけ再実行できます。")
    from app.preparation_routes import lock_project

    lock_project(db, source.project_id)
    if db.scalar(
        select(OperationJob.id)
        .where(
            OperationJob.project_id == source.project_id,
            OperationJob.operation_type == "prepare_outreach",
            OperationJob.status.in_(("queued", "running")),
        )
        .limit(1)
    ):
        raise HTTPException(409, "営業準備が実行中です。停止または完了後に再実行してください。")
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == source.project_id,
            OperationJob.operation_type == source.operation_type,
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active:
        raise HTTPException(409, "同じ種類の処理がすでに実行待ちです。")
    if "condition_binding" in source.payload:
        from app.services.condition_collection import execution_conditions

        try:
            execution_conditions(db, source)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    job = OperationJob(
        project_id=source.project_id,
        operation_type=source.operation_type,
        payload=source.payload,
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "同じ種類の処理がすでに実行待ちです。")
    source.acknowledged_at = datetime.now(timezone.utc)
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
