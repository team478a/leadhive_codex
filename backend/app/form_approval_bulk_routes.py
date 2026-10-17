from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.form_dm_readiness_routes import latest_completed_job
from app.model_approved_form import FormDispatchLimits
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    Company,
    FormAnalysisLog,
    FormDmReadinessResult,
    FormProfile,
    OperationJob,
    User,
)
from app.project_access import project_access
from app.schema_workflow import OperationJobOut
from app.security import current_user
from app.services import human_approval
from app.services.operations import add_operation_job
from app.services.sending_window import allowed

router = APIRouter(prefix="/api/projects", tags=["Form approval batch"])


class FormApprovalBulkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_ids: list[UUID] = Field(default_factory=list, max_length=200)
    all_ready: bool = False

    @model_validator(mode="after")
    def require_scope(self):
        if bool(self.company_ids) == self.all_ready:
            raise ValueError("company_idsまたはall_ready=trueのどちらかを指定してください。")
        if len(self.company_ids) != len(set(self.company_ids)):
            raise ValueError("company_idsに重複があります。")
        return self


@router.post(
    "/{project_id}/form-approval-requests/bulk",
    response_model=OperationJobOut,
    status_code=202,
)
def create_form_approval_batch(
    project_id: UUID,
    body: FormApprovalBulkInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    if body.all_ready:
        snapshot = latest_completed_job(db, project_id)
        if snapshot is None:
            raise HTTPException(409, "フォーム可否の集計を先に完了してください。")
        confirmed_review_exists = (
            select(FormAnalysisLog.id)
            .where(
                FormAnalysisLog.form_profile_id == FormProfile.id,
                FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
                FormAnalysisLog.details["profile_fingerprint"].astext == FormProfile.fingerprint,
                FormAnalysisLog.details["confirmed_no_sales_prohibition"].astext == "true",
            )
            .exists()
        )
        company_ids = list(
            db.scalars(
                select(FormDmReadinessResult.company_id)
                .join(FormProfile, FormProfile.id == FormDmReadinessResult.profile_id)
                .where(
                    FormDmReadinessResult.job_id == snapshot.id,
                    FormDmReadinessResult.primary_reason == "READY",
                    confirmed_review_exists,
                )
                .order_by(FormDmReadinessResult.company_id)
            ).all()
        )
    else:
        company_ids = list(
            db.scalars(
                select(Company.id)
                .where(Company.project_id == project_id, Company.id.in_(body.company_ids))
                .order_by(Company.created_at, Company.id)
            ).all()
        )
        if len(company_ids) != len(body.company_ids):
            raise HTTPException(404, "指定された企業が見つかりません。")
    if not company_ids:
        raise HTTPException(409, "承認提案を作成する企業がありません。")
    job = OperationJob(
        project_id=project_id,
        operation_type="form_approval_batch",
        total_count=len(company_ids),
        payload={
            "company_ids": [str(company_id) for company_id in company_ids],
            "user_id": str(user.id),
            "results": [],
        },
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "フォーム承認提案の一括作成がすでに実行中です。")
    db.commit()
    db.refresh(job)
    return job


@router.get("/{project_id}/form-approval-daily-summary")
def form_approval_daily_summary(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    limits = db.get(FormDispatchLimits, 1)
    if limits is None:
        raise HTTPException(503, "フォーム送信上限設定がありません。")
    now = human_approval.now()
    started_today = (
        db.scalar(
            select(func.count())
            .select_from(ApprovedFormDispatch)
            .where(ApprovedFormDispatch.started_at >= now - timedelta(days=1))
        )
        or 0
    )
    started_approvals = (
        select(ApprovedFormDispatch.id)
        .where(
            ApprovedFormDispatch.approval_id == ApprovalRequest.id,
            ApprovedFormDispatch.started_at.is_not(None),
        )
        .exists()
    )
    approved_unsent = (
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(
                ApprovalRequest.channel == "form",
                ApprovalRequest.delivery_method == "form_direct",
                ApprovalRequest.status == "APPROVED",
                ApprovalRequest.expires_at > now,
                ~started_approvals,
            )
        )
        or 0
    )
    pending = (
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(
                ApprovalRequest.project_id == project_id,
                ApprovalRequest.channel == "form",
                ApprovalRequest.delivery_method == "form_direct",
                ApprovalRequest.status == "PENDING",
                ApprovalRequest.expires_at > now,
            )
        )
        or 0
    )
    within_window = allowed(db, now)
    remaining = max(0, limits.daily_limit - started_today - approved_unsent)
    if limits.paused or not within_window:
        remaining = 0
    return {
        "daily_limit": limits.daily_limit,
        "started_last_24h": started_today,
        "approved_unsent": approved_unsent,
        "pending_approvals": pending,
        "remaining_quota": remaining,
        "paused": limits.paused,
        "within_send_window": within_window,
    }
