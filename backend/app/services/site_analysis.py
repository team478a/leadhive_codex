"""Queue and execute one-job web and form analysis for collected companies."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApplicationSettings, Company, OperationJob
from app.services.operations import add_operation_job
from app.services.scraper import PageFetchCache

QUEUE_CHUNK_SIZE = 200


def auto_site_analysis_enabled(db: Session) -> bool:
    saved = db.get(ApplicationSettings, 1)
    return saved.auto_site_analysis if saved is not None else True


def analyze_site_company(
    db: Session, company: Company, *, force: bool = False, page_cache: PageFetchCache | None = None
) -> bool:
    from app.services.form_intelligence import analyze_company_forms
    from app.services.web_analysis import analyze

    result = analyze(db, company, force, page_cache=page_cache)
    profiles = []
    if result.website_url and result.analysis_status not in {"excluded", "duplicate"}:
        profiles = analyze_company_forms(db, result, force, page_cache=page_cache)
    return result.analysis_status == "completed" and all(
        profile.form_status != "ERROR" for profile in profiles
    )


def enqueue_site_analysis(
    db: Session,
    project_id: UUID,
    company_ids: list[UUID],
    *,
    force: bool = False,
    automatic: bool = False,
    expunge: bool = True,
    extra_payload: dict | None = None,
    preserve_instances: tuple[object, ...] = (),
) -> OperationJob | None:
    if automatic and not auto_site_analysis_enabled(db):
        return None

    unique_ids = list(dict.fromkeys(company_ids))
    if not unique_ids:
        return None

    active: OperationJob | None = None
    active_id: UUID | None = None
    for offset in range(0, len(unique_ids), QUEUE_CHUNK_SIZE):
        chunk = unique_ids[offset : offset + QUEUE_CHUNK_SIZE]
        active = db.scalar(
            select(OperationJob)
            .where(
                OperationJob.project_id == project_id,
                OperationJob.operation_type == "site_analysis",
                OperationJob.status.in_(("queued", "running")),
            )
            .with_for_update()
            .limit(1)
        )
        if active is None:
            active = OperationJob(
                project_id=project_id,
                operation_type="site_analysis",
                payload={
                    "company_ids": [str(value) for value in chunk],
                    "force": force,
                    **(extra_payload or {}),
                },
                total_count=len(chunk),
            )
            if not add_operation_job(db, active):
                active = db.scalar(
                    select(OperationJob)
                    .where(
                        OperationJob.project_id == project_id,
                        OperationJob.operation_type == "site_analysis",
                        OperationJob.status.in_(("queued", "running")),
                    )
                    .with_for_update()
                    .limit(1)
                )
                if active is None:
                    raise RuntimeError("site analysis job creation race could not be resolved")

        payload = dict(active.payload or {})
        queued_ids = list(dict.fromkeys(payload.get("company_ids", [])))
        queued_ids.extend(str(value) for value in chunk if str(value) not in set(queued_ids))
        payload["company_ids"] = queued_ids
        payload["force"] = bool(payload.get("force") or force)
        payload.update(extra_payload or {})
        active.payload = payload
        active.total_count = max(active.total_count, len(queued_ids))
        active_id = active.id
        db.commit()
        if expunge:
            db.expunge_all()
            for instance in preserve_instances:
                db.add(instance)
                db.refresh(instance)

    if active_id is None:
        return None
    return db.get(OperationJob, active_id)


def enqueue_site_analysis_scan(
    db: Session, project_id: UUID, *, force: bool = False
) -> OperationJob:
    active = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "site_analysis",
            OperationJob.status.in_(("queued", "running")),
        )
        .with_for_update()
        .limit(1)
    )
    if active is not None:
        active.payload = {
            **(active.payload or {}),
            "scan_unanalyzed": True,
            "force": bool((active.payload or {}).get("force") or force),
        }
        db.commit()
        db.refresh(active)
        return active

    job = OperationJob(
        project_id=project_id,
        operation_type="site_analysis",
        payload={"company_ids": [], "force": force, "scan_unanalyzed": True},
    )
    if not add_operation_job(db, job):
        active = db.scalar(
            select(OperationJob)
            .where(
                OperationJob.project_id == project_id,
                OperationJob.operation_type == "site_analysis",
                OperationJob.status.in_(("queued", "running")),
            )
            .with_for_update()
            .limit(1)
        )
        if active is None:
            raise RuntimeError("site analysis scan race could not be resolved")
        active.payload = {
            **(active.payload or {}),
            "scan_unanalyzed": True,
            "force": bool((active.payload or {}).get("force") or force),
        }
        job = active
    db.commit()
    db.refresh(job)
    return job


def enqueue_readiness_after_site_analysis(db: Session, project_id: UUID) -> None:
    active = db.scalar(
        select(OperationJob.id)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if active is not None:
        return
    job = OperationJob(
        project_id=project_id,
        operation_type="form_dm_readiness",
        payload={"requested_by_user_id": None, "requested_after_site_analysis": True},
    )
    if add_operation_job(db, job):
        db.commit()
