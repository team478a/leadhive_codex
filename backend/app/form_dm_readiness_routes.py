"""Read-only readiness reasons for approved form outreach."""

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    FormDmReadinessResult,
    FormProfile,
    FormProfileField,
    OperationJob,
    OutreachDraft,
    User,
)
from app.project_access import project_access
from app.schemas import OperationJobOut
from app.security import current_user
from app.services.approved_form import duplicate
from app.services.collection_feedback import latest_company_feedback
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_approval_preparation import preparation
from app.services.non_company_suspected import display_name
from app.services.non_company_suspected import evidence as non_company_evidence
from app.services.operations import add_operation_job

router = APIRouter(prefix="/api", tags=["Form DM readiness"])
PAGE_SIZE = 20
REASONS = (
    "CONTACT_PROHIBITED",
    "NON_COMPANY_SUSPECTED",
    "ALREADY_SENT_OR_UNKNOWN",
    "CAPTCHA_VISIBLE",
    "CAPTCHA_INVISIBLE",
    "CAPTCHA_LEGACY",
    "CF7",
    "JS_SUBMIT",
    "EXTERNAL_ACTION",
    "MULTIPART_OR_FILE",
    "FILE_ATTACHMENT",
    "MULTIPART_ONLY",
    "NON_POST_METHOD",
    "DUPLICATE_INPUTS",
    "MISSING_NAME_ATTRIBUTE",
    "NO_NATIVE_SUBMIT",
    "CUSTOM_SUBMIT_HANDLER",
    "NO_INPUT_FIELDS",
    "JAVASCRIPT_CONFIRMATION",
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
REVIEW_REASONS = {
    "NEEDS_CONSENT_REVIEW",
    "NEEDS_CHOICE_REVIEW",
    "NEEDS_MAPPING_REVIEW",
}
BLOCKING_REASONS = {
    "CONTACT_PROHIBITED",
    "NON_COMPANY_SUSPECTED",
    "ALREADY_SENT_OR_UNKNOWN",
    "CAPTCHA_VISIBLE",
    "CAPTCHA_INVISIBLE",
    "CAPTCHA_LEGACY",
    "CF7",
    "JS_SUBMIT",
    "EXTERNAL_ACTION",
    "MULTIPART_OR_FILE",
    "FILE_ATTACHMENT",
    "MULTIPART_ONLY",
    "NON_POST_METHOD",
    "DUPLICATE_INPUTS",
    "MISSING_NAME_ATTRIBUTE",
    "NO_NATIVE_SUBMIT",
    "CUSTOM_SUBMIT_HANDLER",
    "NO_INPUT_FIELDS",
    "JAVASCRIPT_CONFIRMATION",
    "OTHER_UNSUPPORTED",
    "CONFIRMATION_PAGE",
    "CONFIRMATION_UNKNOWN",
}


COMPATIBILITY_REASONS = {
    "NON_POST_METHOD": "NON_POST_METHOD",
    "DUPLICATE_INPUTS": "DUPLICATE_INPUTS",
    "MISSING_NAME_ATTRIBUTE": "MISSING_NAME_ATTRIBUTE",
    "NO_NATIVE_SUBMIT": "NO_NATIVE_SUBMIT",
    "CUSTOM_SUBMIT_HANDLER": "CUSTOM_SUBMIT_HANDLER",
    "NO_INPUT_FIELDS": "NO_INPUT_FIELDS",
    "JAVASCRIPT_CONFIRMATION": "JAVASCRIPT_CONFIRMATION",
    "CONTACT_FORM_7": "CF7",
    "ASYNC_SUBMISSION": "JS_SUBMIT",
    "EXTERNAL_ACTION": "EXTERNAL_ACTION",
    "INSECURE_ACTION": "EXTERNAL_ACTION",
    "PASSWORD_FIELD": "OTHER_UNSUPPORTED",
}


def _compatibility_reason(db: Session, profile: FormProfile) -> str | None:
    reason_code = profile.compatibility_reason_code or ""
    if reason_code == "MULTIPART_OR_FILE":
        file_field = db.scalar(
            select(FormProfileField.id)
            .where(
                FormProfileField.form_profile_id == profile.id,
                FormProfileField.field_type == "file",
            )
            .limit(1)
        )
        return "FILE_ATTACHMENT" if file_field else "MULTIPART_ONLY"
    if reason_code in COMPATIBILITY_REASONS:
        return COMPATIBILITY_REASONS[reason_code]
    text = (profile.review_reason or "").casefold()
    if "contact form 7" in text or "wpcf7" in text:
        return "CF7"
    if "javascript" in text or "非同期" in text or "ajax" in text:
        return "JS_SUBMIT"
    if "外部サイト" in text or "external" in text:
        return "EXTERNAL_ACTION"
    if "multipart" in text or "ファイル" in text or "添付" in text:
        file_field = db.scalar(
            select(FormProfileField.id)
            .where(
                FormProfileField.form_profile_id == profile.id,
                FormProfileField.field_type == "file",
            )
            .limit(1)
        )
        return "FILE_ATTACHMENT" if file_field else "MULTIPART_ONLY"
    if not profile.delivery_supported:
        return "OTHER_UNSUPPORTED"
    return None


def _preparation_reason(message: str, captcha_reason: str | None = None) -> str:
    text = message.casefold()
    if "captcha" in text:
        return captcha_reason or "OTHER_UNSUPPORTED"
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
    company_evidence = non_company_evidence(company)
    company_feedback = (
        latest_company_feedback(db, company)
        if company_evidence or company.status == "excluded"
        else None
    )
    if not (
        company_feedback
        and company_feedback.get("outcome") == "OK"
        and company_feedback.get("reason") == "company_verified"
    ):
        if (
            company_feedback
            and company_feedback.get("outcome") == "NG"
            and company_feedback.get("reason") == "wrong_company"
        ):
            company_evidence = list(dict.fromkeys(["NON_COMPANY_REVIEW_NG", *company_evidence]))
        if company_evidence:
            reasons.extend(["NON_COMPANY_SUSPECTED", *company_evidence])
    if permission.reason_code == "form_result_unknown" or duplicate(
        db, company.id, profile.form_url
    ):
        reasons.append("ALREADY_SENT_OR_UNKNOWN")
    captcha_type = profile.captcha_type
    if captcha_type == "CAPTCHA_RECAPTCHA":
        captcha_reason = "CAPTCHA_LEGACY"
    elif captcha_type in {"CAPTCHA_RECAPTCHA_V3", "CAPTCHA_CF7_RECAPTCHA"}:
        captcha_reason = "CAPTCHA_INVISIBLE"
    elif captcha_type != "CAPTCHA_NONE":
        captcha_reason = "CAPTCHA_VISIBLE"
    else:
        captcha_reason = None
    if captcha_reason:
        reasons.append(captcha_reason)
    compatibility = _compatibility_reason(db, profile)
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
            mapped = _preparation_reason(
                f"{exc.detail} {profile.review_reason or ''}", captcha_reason
            )
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
    suspected_only: bool = Query(False),
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
        suspected_filter = or_(
            FormDmReadinessResult.primary_reason == "NON_COMPANY_SUSPECTED",
            FormDmReadinessResult.secondary_reasons.contains(["NON_COMPANY_SUSPECTED"]),
        )
        result_filters = [FormDmReadinessResult.job_id == snapshot.id]
        if suspected_only:
            result_filters.append(suspected_filter)
            total = (
                db.scalar(
                    select(func.count()).where(
                        FormDmReadinessResult.job_id == snapshot.id,
                        suspected_filter,
                    )
                )
                or 0
            )
        else:
            total = sum(counts.values())
        captcha_counts = db.execute(
            select(
                *[
                    func.sum(
                        case(
                            (
                                or_(
                                    FormDmReadinessResult.primary_reason == reason,
                                    FormDmReadinessResult.secondary_reasons.contains([reason]),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label(reason)
                    for reason in (
                        "CAPTCHA_VISIBLE",
                        "CAPTCHA_INVISIBLE",
                        "CAPTCHA_LEGACY",
                    )
                ]
            ).where(FormDmReadinessResult.job_id == snapshot.id)
        ).one()
        counts.update({reason: value or 0 for reason, value in captcha_counts._mapping.items()})
        counts["NON_COMPANY_SUSPECTED"] = (
            db.scalar(
                select(func.count()).where(
                    FormDmReadinessResult.job_id == snapshot.id,
                    suspected_filter,
                )
            )
            or 0
        )
        if format == "json":
            rows = db.execute(
                select(FormDmReadinessResult, Company, FormProfile)
                .join(Company, Company.id == FormDmReadinessResult.company_id)
                .join(FormProfile, FormProfile.id == FormDmReadinessResult.profile_id)
                .where(*result_filters)
                .order_by(Company.company_name, Company.id)
                .offset(offset)
                .limit(PAGE_SIZE)
            ).all()
            items = [
                {
                    "company_id": str(result.company_id),
                    "company_name": display_name(company),
                    "company_updated_at": company.updated_at,
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
                    .where(*result_filters)
                    .order_by(Company.company_name, Company.id)
                    .execution_options(stream_results=True, yield_per=200)
                )
                for result, company, profile in result_rows:
                    writer.writerow(
                        [
                            result.company_id,
                            display_name(company),
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
            # A concurrent request may have inserted the active job after the
            # initial lookup. Return that job so the caller can follow progress.
            job = db.scalar(
                select(OperationJob)
                .where(
                    OperationJob.project_id == project_id,
                    OperationJob.operation_type == "form_dm_readiness",
                    OperationJob.status.in_(("queued", "running")),
                )
                .order_by(OperationJob.created_at.desc())
                .limit(1)
            )
            if job is None:
                raise HTTPException(
                    409, "フォームDMの再集計を開始できませんでした。再試行してください。"
                )
        else:
            db.commit()
            db.refresh(job)
    return OperationJobOut.model_validate(job)
