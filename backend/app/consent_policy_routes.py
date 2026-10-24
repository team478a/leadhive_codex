from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OperationJob, OutreachAuditEvent, Project, User
from app.project_access import project_access
from app.schema_core import Input
from app.schemas import OperationJobOut
from app.security import current_user
from app.services.form_intelligence.consent import (
    CONSENT_POLICY_CONDITIONS,
    CONSENT_POLICY_VERSION,
)
from app.services.operations import add_operation_job

router = APIRouter(prefix="/api", tags=["Consent policy"])


class ConsentPolicyConfirmation(Input):
    policy: str = Field(pattern=f"^{CONSENT_POLICY_VERSION}$")
    accepted: StrictBool


def _active_job(db: Session, project_id: UUID) -> OperationJob | None:
    return db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "consent_policy",
            OperationJob.status.in_(("queued", "running")),
        )
        .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
        .limit(1)
    )


def _enqueue(db: Session, project_id: UUID, user: User, action: str) -> OperationJob:
    if _active_job(db, project_id) is not None:
        raise HTTPException(409, "同意欄ルールの処理がすでに実行中です。")
    job = OperationJob(
        project_id=project_id,
        operation_type="consent_policy",
        payload={
            "action": action,
            "policy": CONSENT_POLICY_VERSION,
            "requested_by_user_id": str(user.id),
        },
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "同意欄ルールの処理がすでに実行中です。")
    return job


def _status(project: Project, user: User, active_job: OperationJob | None) -> dict:
    return {
        "policy": CONSENT_POLICY_VERSION,
        "conditions": list(CONSENT_POLICY_CONDITIONS),
        "enabled": project.consent_policy_enabled,
        "enabled_at": project.consent_policy_enabled_at,
        "can_manage": project.user_id == user.id,
        "active_job": OperationJobOut.model_validate(active_job) if active_job else None,
    }


@router.get("/projects/{project_id}/consent-policy")
def get_consent_policy(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project = project_access(project_id, db, user, write=False)
    return _status(project, user, _active_job(db, project_id))


@router.post("/projects/{project_id}/consent-policy/enable", status_code=202)
def enable_consent_policy(
    project_id: UUID,
    body: ConsentPolicyConfirmation,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.accepted:
        raise HTTPException(422, "条件を確認し、承認してください。")
    project_access(project_id, db, user, owner=True)
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    job = _enqueue(db, project_id, user, "apply")
    now = datetime.now(timezone.utc)
    project.consent_policy_enabled = True
    project.consent_policy_version = CONSENT_POLICY_VERSION
    project.consent_policy_enabled_by_user_id = user.id
    project.consent_policy_enabled_at = now
    db.add(
        OutreachAuditEvent(
            event="consent policy enabled",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            before_status="DISABLED",
            after_status="ENABLED",
            reason=f"policy={CONSENT_POLICY_VERSION}",
        )
    )
    db.commit()
    db.refresh(job)
    return {"setting": _status(project, user, job), "job": OperationJobOut.model_validate(job)}


@router.post("/projects/{project_id}/consent-policy/disable")
def disable_consent_policy(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, owner=True)
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    project.consent_policy_enabled = False
    db.add(
        OutreachAuditEvent(
            event="consent policy disabled",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            before_status="ENABLED",
            after_status="DISABLED",
            reason=f"policy={CONSENT_POLICY_VERSION}; decisions preserved",
        )
    )
    db.commit()
    return _status(project, user, _active_job(db, project_id))


@router.post("/projects/{project_id}/consent-policy/reset", status_code=202)
def reset_consent_policy(
    project_id: UUID,
    body: ConsentPolicyConfirmation,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.accepted:
        raise HTTPException(422, "取り消す内容を確認してください。")
    project = project_access(project_id, db, user, owner=True)
    job = _enqueue(db, project_id, user, "reset")
    db.add(
        OutreachAuditEvent(
            event="consent policy reset requested",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            before_status="POLICY",
            after_status="RULE",
            reason=f"policy={CONSENT_POLICY_VERSION}; manual decisions preserved",
        )
    )
    db.commit()
    db.refresh(job)
    return {"setting": _status(project, user, job), "job": OperationJobOut.model_validate(job)}
