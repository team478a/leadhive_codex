from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, not_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.form_dm_readiness_routes import latest_completed_job
from app.models import (
    ApprovalRequest,
    ApprovedEmailReservation,
    ApprovedFormDispatch,
    Company,
    EmailDelivery,
    FormAnalysisLog,
    FormDelivery,
    FormDmReadinessResult,
    FormProfile,
    OperationJob,
    OutreachDraft,
    OutreachTemplate,
    User,
)
from app.project_access import project_access
from app.schema_outreach import BulkFormDraftTargetsOut, BulkOutreachDraftInput
from app.schema_workflow import OperationJobOut
from app.security import current_user
from app.services.bulk_template_drafts import (
    email_draft_targets,
    readiness_target_summary,
    readiness_targets,
)
from app.services.operations import add_operation_job
from app.services.outreach_template_validation import has_stop_method

router = APIRouter(prefix="/api", tags=["Send flow"])
SEND_FLOW_JOB = "bulk_template_drafts"


@router.get(
    "/projects/{project_id}/outreach-drafts/bulk-from-template/form-targets",
    response_model=BulkFormDraftTargetsOut,
)
def bulk_form_draft_targets(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    return readiness_target_summary(db, project_id)


@router.post(
    "/projects/{project_id}/outreach-drafts/bulk-from-template",
    response_model=OperationJobOut,
    status_code=202,
)
def enqueue_bulk_template_drafts(
    project_id: UUID,
    body: BulkOutreachDraftInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    if body.channel == "form" and db.scalar(
        select(OperationJob.id)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status == "running",
        )
        .limit(1)
    ):
        raise HTTPException(409, "送信可否の再集計中です。完了後に下書きを作成してください。")
    template = db.scalar(
        select(OutreachTemplate).where(
            OutreachTemplate.id == body.template_id,
            OutreachTemplate.project_id == project_id,
        )
    )
    if template is None:
        raise HTTPException(404, "営業文面テンプレートが見つかりません。")
    if template.channel != body.channel:
        raise HTTPException(409, "テンプレートの連絡経路が一致しません。")
    if not has_stop_method(template.channel, template.body):
        raise HTTPException(
            409,
            "テンプレートを編集し、配信停止・連絡辞退の方法を追加してください。",
        )

    if body.readiness_reason == "NO_FORM_DRAFT":
        targets = readiness_targets(db, project_id)
    elif body.readiness_reason == "NO_EMAIL_DRAFT":
        targets = email_draft_targets(db, project_id)
    else:
        rows = db.scalars(
            select(Company.id).where(
                Company.project_id == project_id,
                Company.id.in_(body.company_ids),
            )
        ).all()
        if len(rows) != len(body.company_ids):
            raise HTTPException(404, "対象企業が見つからないか、プロジェクトに属していません。")
        targets = [{"company_id": str(company_id), "profile_id": None} for company_id in rows]
    if not targets:
        raise HTTPException(409, "一括作成できる企業がありません。")

    job = OperationJob(
        project_id=project_id,
        operation_type=SEND_FLOW_JOB,
        total_count=len(targets),
        payload={
            "template_id": str(template.id),
            "channel": body.channel,
            "targets": targets,
            "user_id": str(user.id),
            "bulk_template_results": {
                "created": [],
                "skipped_existing": [],
                "excluded": [],
            },
        },
    )
    if not add_operation_job(db, job):
        active_job = db.scalar(
            select(OperationJob)
            .where(
                OperationJob.project_id == project_id,
                OperationJob.operation_type == SEND_FLOW_JOB,
                OperationJob.status.in_(("queued", "running")),
            )
            .limit(1)
        )
        return active_job
    db.commit()
    db.refresh(job)
    return job


def _tokyo_day_bounds() -> tuple[datetime, datetime]:
    tokyo = timezone(timedelta(hours=9))
    today = datetime.now(tokyo).date()
    start = datetime.combine(today, time.min, tzinfo=tokyo)
    end = datetime.combine(today, time.max, tzinfo=tokyo)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@router.get("/projects/{project_id}/send-flow-summary")
def send_flow_summary(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    snapshot = latest_completed_job(db, project_id)
    target_count = (
        db.scalar(
            select(func.count())
            .select_from(FormDmReadinessResult)
            .where(FormDmReadinessResult.job_id == snapshot.id)
        )
        if snapshot
        else 0
    ) or 0

    draft_counts = {"email": 0, "form": 0}
    rows = db.execute(
        select(OutreachDraft.channel, func.count(), func.max(OutreachDraft.updated_at))
        .join(Company, Company.id == OutreachDraft.company_id)
        .where(Company.project_id == project_id, OutreachDraft.channel.in_(("email", "form")))
        .group_by(OutreachDraft.channel)
    ).all()
    draft_counts.update({channel: count for channel, count, _latest_updated_at in rows})
    latest_form_draft_updated_at = next(
        (latest_updated_at for channel, _count, latest_updated_at in rows if channel == "form"),
        None,
    )

    reviewed_count = (
        db.scalar(
            select(func.count(func.distinct(Company.id)))
            .select_from(FormAnalysisLog)
            .join(FormProfile, FormProfile.id == FormAnalysisLog.form_profile_id)
            .join(Company, Company.id == FormProfile.company_id)
            .where(
                Company.project_id == project_id,
                FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
                FormAnalysisLog.details["profile_fingerprint"].astext == FormProfile.fingerprint,
            )
        )
        or 0
    )

    approval_counts = {
        "pending": {"email": 0, "form": 0},
        "approved_unsent": {"email": 0, "form": 0},
    }
    now = datetime.now(timezone.utc)
    reserved_email = (
        select(ApprovedEmailReservation.id)
        .where(ApprovedEmailReservation.approval_id == ApprovalRequest.id)
        .exists()
    )
    reserved_form = (
        select(ApprovedFormDispatch.id)
        .where(ApprovedFormDispatch.approval_id == ApprovalRequest.id)
        .exists()
    )
    approved_rows = db.execute(
        select(
            ApprovalRequest.channel,
            func.sum(case((ApprovalRequest.status == "PENDING", 1), else_=0)).label("pending"),
            func.sum(
                case(
                    (
                        (ApprovalRequest.status == "APPROVED")
                        & (ApprovalRequest.expires_at > now)
                        & not_(reserved_email)
                        & not_(reserved_form),
                        1,
                    ),
                    else_=0,
                )
            ).label("approved_unsent"),
        )
        .where(
            ApprovalRequest.project_id == project_id,
            ApprovalRequest.status.in_(("PENDING", "APPROVED")),
            ApprovalRequest.channel.in_(("email", "form")),
        )
        .group_by(ApprovalRequest.channel)
    ).all()
    for channel, pending, approved_unsent in approved_rows:
        approval_counts["pending"][channel] = pending or 0
        approval_counts["approved_unsent"][channel] = approved_unsent or 0

    start, end = _tokyo_day_bounds()
    email_metrics = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            (EmailDelivery.status == "sent")
                            & EmailDelivery.sent_at.between(start, end),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("today_sent"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            EmailDelivery.status.in_(("queued", "running"))
                            & EmailDelivery.scheduled_for.between(start, end),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("today_reserved"),
            func.count(case((EmailDelivery.status == "sent", 1))).label("sent"),
            func.count(case((EmailDelivery.status == "failed", 1))).label("failed"),
            func.count(case((EmailDelivery.status == "unknown", 1))).label("unknown"),
        )
        .select_from(EmailDelivery)
        .join(Company, Company.id == EmailDelivery.company_id)
        .where(Company.project_id == project_id)
    ).one()

    form_metrics = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            (FormDelivery.status == "submitted")
                            & FormDelivery.submitted_at.between(start, end),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("today_sent"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (FormDelivery.status == "pending")
                            & FormDelivery.created_at.between(start, end),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("today_reserved"),
            func.count(case((FormDelivery.status == "submitted", 1))).label("sent"),
            func.count(case((FormDelivery.status == "failed", 1))).label("failed"),
            func.count(case((FormDelivery.status == "unknown", 1))).label("unknown"),
        )
        .select_from(FormDelivery)
        .join(Company, Company.id == FormDelivery.company_id)
        .where(Company.project_id == project_id)
    ).one()

    dispatch_metrics = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            ApprovedFormDispatch.status.in_(("queued", "checking"))
                            & ApprovedFormDispatch.created_at.between(start, end),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("today_reserved"),
            func.count(
                case(
                    (
                        (ApprovedFormDispatch.status == "submitted")
                        & ApprovedFormDispatch.delivery_id.is_(None),
                        1,
                    )
                )
            ).label("sent_without_delivery"),
            func.count(
                case(
                    (
                        (ApprovedFormDispatch.status == "failed")
                        & ApprovedFormDispatch.delivery_id.is_(None),
                        1,
                    )
                )
            ).label("failed_without_delivery"),
            func.count(
                case(
                    (
                        (ApprovedFormDispatch.status == "unknown")
                        & ApprovedFormDispatch.delivery_id.is_(None),
                        1,
                    )
                )
            ).label("unknown_without_delivery"),
        ).where(ApprovedFormDispatch.project_id == project_id)
    ).one()

    return {
        "readiness_completed_at": snapshot.finished_at if snapshot else None,
        "latest_form_draft_updated_at": latest_form_draft_updated_at,
        "target_company_count": target_count,
        "draft_counts": draft_counts,
        "form_reviewed_count": reviewed_count,
        "approval_counts": approval_counts,
        "today": {
            "sent": email_metrics.today_sent + form_metrics.today_sent,
            "reserved": (
                email_metrics.today_reserved
                + form_metrics.today_reserved
                + dispatch_metrics.today_reserved
            ),
        },
        "results": {
            "sent": email_metrics.sent + form_metrics.sent + dispatch_metrics.sent_without_delivery,
            "failed": email_metrics.failed
            + form_metrics.failed
            + dispatch_metrics.failed_without_delivery,
            "unknown": email_metrics.unknown
            + form_metrics.unknown
            + dispatch_metrics.unknown_without_delivery,
        },
    }
