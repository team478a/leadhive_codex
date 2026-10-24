from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FormProfile, FormProfileField
from app.services.form_intelligence.fields import mapping_review_reason

TECHNICAL_FIELD_TYPES = ("hidden", "submit", "button", "reset", "image")


def field_material(field: FormProfileField) -> dict:
    return {
        key: getattr(field, key)
        for key in (
            "field_type",
            "label",
            "mapped_key",
            "confidence",
            "required",
            "options",
            "recommended_value",
            "decision_source",
        )
    }


def recompute_stored_profile_status(db: Session, profile: FormProfile) -> str:
    fields = db.scalars(
        select(FormProfileField).where(
            FormProfileField.form_profile_id == profile.id,
            ~FormProfileField.field_type.in_(TECHNICAL_FIELD_TYPES),
        )
    ).all()
    mapping_reason = mapping_review_reason([field_material(item) for item in fields])
    if profile.sales_contact_status == "PROHIBITED":
        profile.form_status = "BLOCKED"
        profile.review_reason = "営業禁止を検出しました。送信対象から除外します。"
    elif profile.form_status in {"STALE", "ERROR", "BLOCKED"}:
        profile.delivery_supported = False
    elif (
        not profile.form_found
        or profile.sales_contact_status == "UNCERTAIN"
        or profile.captcha_type != "CAPTCHA_NONE"
        or not profile.delivery_supported
        or profile.confirmation_page is None
        or mapping_reason
    ):
        profile.form_status = "REVIEW_REQUIRED"
        if not profile.delivery_supported and not profile.review_reason:
            profile.review_reason = "このフォームはブラウザまたはCodex支援での操作が必要です。"
        elif mapping_reason:
            profile.review_reason = mapping_reason
    else:
        profile.form_status = "READY"
        profile.review_reason = ""
    return profile.form_status
