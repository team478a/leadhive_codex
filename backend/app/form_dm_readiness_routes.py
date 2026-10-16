"""Read-only readiness reasons for approved form outreach."""

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    FormProfile,
    OutreachDraft,
    User,
)
from app.project_access import project_access
from app.security import current_user
from app.services.approved_form import duplicate
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_approval_preparation import preparation

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
    text = (profile.compatibility_reason or "").casefold()
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


def _rows(db: Session, project_id: UUID) -> list[tuple[Company, FormProfile]]:
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
    return list(
        db.execute(
            select(Company, FormProfile)
            .join(ranked, (ranked.c.company_id == Company.id) & (ranked.c.position == 1))
            .join(FormProfile, FormProfile.id == ranked.c.profile_id)
            .where(Company.project_id == project_id, FormProfile.form_found.is_(True))
            .order_by(Company.company_name, Company.id)
        ).all()
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
    rows = _rows(db, project_id)
    classified = []
    counts = {reason: 0 for reason in REASONS}
    for company, profile in rows:
        result = classify_profile(db, company, profile)
        counts[result["primary_reason"]] += 1
        classified.append(
            {
                "company_id": str(company.id),
                "company_name": company.company_name,
                "form_url": profile.form_url,
                "primary_reason": result["primary_reason"],
                "secondary_reasons": result["secondary_reasons"],
            }
        )
    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            ["company_id", "company_name", "form_url", "primary_reason", "secondary_reasons"]
        )
        for item in classified:
            writer.writerow(
                [
                    item["company_id"],
                    item["company_name"],
                    item["form_url"],
                    item["primary_reason"],
                    ",".join(item["secondary_reasons"]),
                ]
            )
        from fastapi.responses import Response

        return Response(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=form-dm-readiness.csv"},
        )
    return {
        "counts": counts,
        "total": len(classified),
        "offset": offset,
        "limit": PAGE_SIZE,
        "items": classified[offset : offset + PAGE_SIZE],
        "read_only": True,
        "external_requests": 0,
    }
