from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_routes import owned_project
from app.database import get_db
from app.models import OperationJob, Project, User
from app.schemas import OperationJobInput, OperationJobOut
from app.security import current_user

router = APIRouter(prefix="/api")


def owned_operation(job_id: UUID, db: Session, user: User) -> OperationJob:
    job = db.scalar(
        select(OperationJob)
        .join(Project, Project.id == OperationJob.project_id)
        .where(OperationJob.id == job_id, Project.user_id == user.id)
    )
    if job is None:
        raise HTTPException(404, "処理ジョブが見つかりません。")
    return job


@router.post("/projects/{project_id}/operations", response_model=OperationJobOut, status_code=202)
def enqueue_operation(
    project_id: UUID,
    body: OperationJobInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_project(project_id, db, user)
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
    owned_project(project_id, db, user)
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
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
