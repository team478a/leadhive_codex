"""Read-only readiness reasons for approved form outreach."""

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    FormDmReadinessResult,
    FormProfile,
    OperationJob,
    OutreachDraft,
    User,
)
from app.project_access import project_access
from app.schemas import OperationJobOut
from app.security import current_user
from app.services.approved_form import duplicate
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_approval_preparation import preparation
from app.services.operations import add_operation_job

router = APIRouter(prefix="/api", tags=["Form DM readiness"])
PAGE_SIZE = 20
REASONS = (
    "CONTACT_PROHIBITED",
    "ALREADY_SENT_OR_UNKNOWN",
    "CAPTCHA",
    "CF7",
    "JS_SUBMIT",
    "EXTERNAL_ACTION",
    "MULTIPART_OR_FILE",
    "OTHER_UNSUPPORTED",
    "CONFIRMATION_PAGE",
    "CONFIRMATION_UNKNOWN",
    "NEEDS_CONSENT_REVIEW",
    "NEEDS_CHOICE_REVIEW",
    "NEEDS_MAPPING_REVIEW",
    "NO_FORM_DRAFT",
    "SENDER_SETTINGS",
    "READY",
)


def _compatibility_reason(profile: FormProfile) -> str | None:
    text = (profile.review_reason or "").casefold()
    if "contact form 7" in text or "wpcf7" in text:
        return "CF7"
    if "javascript" in text or "非同期" in text or "ajax" in text:
        return "JS_SUBMIT"
    if "外部サイト" in text or "external" in text:
        return "EXTERNAL_ACTION"
    if "multipart" in text or "ファイル" in text or "添付" in text:
        return "MULTIPART_OR_FILE"
    if not profile.delivery_supported:
        return "OTHER_UNSUPPORTED"
    return None


def _preparation_reason(message: str) -> str:
    text = message.casefold()
    if "captcha" in text:
        return "CAPTCHA"
    if any(word in text for word in ("連絡禁止", "送信できません", "suppression")):
        return "CONTACT_PROHIBITED"
    if any(word in text for word in ("同意", "consent", "個人情報", "メルマガ")):
        return "NEEDS_CONSENT_REVIEW"
    if any(word in text for word in ("選択", "choice", "選択肢", "種別", "連絡方法")):
        return "NEEDS_CHOICE_REVIEW"
    if "送信者" in text or "sender" in text or "メールアドレス" in text:
        return "SENDER_SETTINGS"
    if "必須" in text or "本文" in text or "入力項目" in text or "mapping" in text:
        return "NEEDS_MAPPING_REVIEW"
    return "OTHER_UNSUPPORTED"


def classify_profile(db: Session, company: Company, profile: FormProfile) -> dict:
    """Use existing safety and preparation checks; never fetch or send."""
    reasons: list[str] = []
    permission = evaluate_contact_permission(
        db, company.project_id, company.id, "form", profile.form_url
    )
    if permission.reason_code in {
        "company_do_not_contact",
        "suppression_email",
        "suppression_domain",
        "suppression_phone",
        "shared_location_destination",
        "form_sales_prohibited",
        "destination_missing",
    }:
        reasons.append("CONTACT_PROHIBITED")
    if permission.reason_code == "form_result_unknown" or duplicate(
        db, company.id, profile.form_url
    ):
        reasons.append("ALREADY_SENT_OR_UNKNOWN")
    if profile.captcha_type != "CAPTCHA_NONE":
        reasons.append("CAPTCHA")
    compatibility = _compatibility_reason(profile)
    if compatibility:
        reasons.append(compatibility)
    if profile.confirmation_page is True:
        reasons.append("CONFIRMATION_PAGE")
    elif profile.confirmation_page is None:
        reasons.append("CONFIRMATION_UNKNOWN")

    draft = db.scalar(
        select(OutreachDraft)
        .where(OutreachDraft.company_id == company.id, OutreachDraft.channel == "form")
        .order_by(OutreachDraft.updated_at.desc(), OutreachDraft.id.desc())
        .limit(1)
    )
    if not draft:
        reasons.append("NO_FORM_DRAFT")
    else:
        try:
            proposal, _preview = preparation(db, company, draft)
            if proposal.channel != "form":
                reasons.append("OTHER_UNSUPPORTED")
        except HTTPException as exc:
            mapped = _preparation_reason(f"{exc.detail} {profile.review_reason or ''}")
            if mapped not in reasons:
                reasons.append(mapped)

    if not reasons:
        reasons.append("READY")
    return {"primary_reason": reasons[0], "secondary_reasons": reasons[1:]}


def _ranked_form_rows(project_id: UUID):
    ranked = (
        select(
            FormProfile.id.label("profile_id"),
            FormProfile.company_id.label("company_id"),
            func.row_number()
            .over(
                partition_by=FormProfile.company_id,
                order_by=(
                    FormProfile.is_primary.desc(),
                    FormProfile.updated_at.desc(),
                    FormProfile.id,
                ),
            )
            .label("position"),
        )
        .join(Company, Company.id == FormProfile.company_id)
        .where(Company.project_id == project_id)
        .subquery()
    )
    return (
        select(Company, FormProfile)
        .join(ranked, (ranked.c.company_id == Company.id) & (ranked.c.position == 1))
        .join(FormProfile, FormProfile.id == ranked.c.profile_id)
        .where(Company.project_id == project_id, FormProfile.form_found.is_(True))
        .order_by(Company.company_name, Company.id)
    )


def latest_completed_job(db: Session, project_id: UUID) -> OperationJob | None:
    return db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status == "completed",
        )
        .order_by(OperationJob.finished_at.desc(), OperationJob.id.desc())
        .limit(1)
    )


@router.get("/projects/{project_id}/form-dm-readiness")
def form_dm_readiness(
    project_id: UUID,
    offset: int = Query(0, ge=0),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    counts = {reason: 0 for reason in REASONS}
    snapshot = latest_completed_job(db, project_id)
    active_job = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status.in_(("queued", "running")),
        )
        .order_by(OperationJob.created_at.desc())
        .limit(1)
    )
    total = 0
    items = []
    if snapshot:
        grouped_counts = db.execute(
            select(FormDmReadinessResult.primary_reason, func.count())
            .where(FormDmReadinessResult.job_id == snapshot.id)
            .group_by(FormDmReadinessResult.primary_reason)
        ).all()
        counts.update({reason: count for reason, count in grouped_counts})
        total = sum(counts.values())
        if format == "json":
            rows = db.execute(
                select(FormDmReadinessResult, Company, FormProfile)
                .join(Company, Company.id == FormDmReadinessResult.company_id)
                .join(FormProfile, FormProfile.id == FormDmReadinessResult.profile_id)
                .where(FormDmReadinessResult.job_id == snapshot.id)
                .order_by(Company.company_name, Company.id)
                .offset(offset)
                .limit(PAGE_SIZE)
            ).all()
            items = [
                {
                    "company_id": str(result.company_id),
                    "company_name": company.company_name,
                    "form_url": profile.form_url,
                    "primary_reason": result.primary_reason,
                    "secondary_reasons": result.secondary_reasons,
                }
                for result, company, profile in rows
            ]
    if format == "csv":

        def csv_rows():
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(
                ["company_id", "company_name", "form_url", "primary_reason", "secondary_reasons"]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            if snapshot:
                result_rows = db.execute(
                    select(FormDmReadinessResult, Company, FormProfile)
                    .join(Company, Company.id == FormDmReadinessResult.company_id)
                    .join(FormProfile, FormProfile.id == FormDmReadinessResult.profile_id)
                    .where(FormDmReadinessResult.job_id == snapshot.id)
                    .order_by(Company.company_name, Company.id)
                    .execution_options(stream_results=True, yield_per=200)
                )
                for result, company, profile in result_rows:
                    writer.writerow(
                        [
                            result.company_id,
                            company.company_name,
                            profile.form_url,
                            result.primary_reason,
                            ",".join(result.secondary_reasons),
                        ]
                    )
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)

        return StreamingResponse(
            csv_rows(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=form-dm-readiness.csv"},
        )
    return {
        "counts": counts,
        "total": total,
        "offset": offset,
        "limit": PAGE_SIZE,
        "items": items,
        "last_aggregated_at": snapshot.finished_at if snapshot else None,
        "active_job": OperationJobOut.model_validate(active_job) if active_job else None,
        "read_only": True,
        "external_requests": 0,
    }


@router.post("/projects/{project_id}/form-dm-readiness/recalculate", status_code=202)
def recalculate_form_dm_readiness(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    active_job = db.scalar(
        select(OperationJob.id)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if active_job:
        job = db.get(OperationJob, active_job)
    else:
        job = OperationJob(
            project_id=project_id,
            operation_type="form_dm_readiness",
            payload={"requested_by_user_id": str(user.id)},
        )
        if not add_operation_job(db, job):
            raise HTTPException(409, "フォームDMの再集計がすでに実行中です。")
        db.commit()
        db.refresh(job)
    return OperationJobOut.model_validate(job)
