from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
)
from app.services.form_delivery import FormDeliveryError, FormPreview, inspect_form


@dataclass(frozen=True)
class DeliveryProfileContext:
    profile: FormProfile
    fields: list[FormProfileField]
    preview: FormPreview
    values: dict[str, str]


STATUS_MESSAGES = {
    "UNANALYZED": "フォーム解析を実行してください。",
    "REVIEW_REQUIRED": "このフォームは確認が必要です。Codex支援を利用してください。",
    "BLOCKED": "営業目的の送信が禁止されているフォームです。",
    "STALE": "フォームが変更されています。再解析してください。",
    "ERROR": "フォーム解析に失敗しています。再解析してください。",
}


def primary_form_profile(db: Session, company_id) -> FormProfile | None:
    return db.scalar(
        select(FormProfile)
        .where(FormProfile.company_id == company_id)
        .order_by(FormProfile.is_primary.desc(), FormProfile.updated_at.desc(), FormProfile.id)
        .limit(1)
    )


def primary_form_profiles(db: Session, company_ids: list) -> dict:
    if not company_ids:
        return {}
    profiles = db.scalars(
        select(FormProfile)
        .where(FormProfile.company_id.in_(company_ids))
        .order_by(
            FormProfile.company_id,
            FormProfile.is_primary.desc(),
            FormProfile.updated_at.desc(),
            FormProfile.id,
        )
    ).all()
    selected = {}
    for profile in profiles:
        selected.setdefault(profile.company_id, profile)
    return selected


def profile_form_url(db: Session, company: Company) -> str:
    profile = primary_form_profile(db, company.id)
    if profile and profile.sales_contact_status == "PROHIBITED":
        raise FormDeliveryError(STATUS_MESSAGES["BLOCKED"], "blocked")
    return profile.form_url if profile and profile.form_found else company.contact_url


def _ready_profile(db: Session, company: Company) -> tuple[FormProfile, list[FormProfileField]]:
    profile = primary_form_profile(db, company.id)
    if profile is None:
        raise FormDeliveryError(
            "フォーム解析が未実行です。先にフォーム解析を実行してください。",
            "unanalyzed",
        )
    if profile.form_status != "READY":
        raise FormDeliveryError(
            STATUS_MESSAGES.get(profile.form_status, "このフォームは自動送信できません。"),
            profile.form_status.lower(),
        )
    if profile.sales_contact_status != "ALLOWED":
        raise FormDeliveryError("営業利用可否を確認してください。", "manual_required")
    if profile.captcha_type != "CAPTCHA_NONE":
        raise FormDeliveryError(
            "CAPTCHA付きフォームはCodex支援を利用してください。", "manual_required"
        )
    fields = list(
        db.scalars(
            select(FormProfileField)
            .where(FormProfileField.form_profile_id == profile.id)
            .order_by(FormProfileField.position)
        ).all()
    )
    return profile, fields


def _sender_values(settings: FormSenderSettings | None) -> dict[str, str]:
    if settings is None:
        return {}
    values = {
        key: str(getattr(settings, key, "") or "").strip()
        for key in (
            "company_name",
            "department",
            "position",
            "contact_name",
            "last_name",
            "first_name",
            "furigana",
            "email",
            "phone",
            "postal_code",
            "prefecture",
            "city",
            "address",
            "building",
            "website",
        )
    }
    if not values["contact_name"]:
        values["contact_name"] = " ".join(
            value for value in (values["last_name"], values["first_name"]) if value
        )
    return values


def mapped_values(
    preview: FormPreview,
    draft: OutreachDraft,
    settings: FormSenderSettings | None,
) -> dict[str, str]:
    sources = _sender_values(settings) | {
        "subject": draft.subject.strip(),
        "message": draft.body.strip(),
    }
    values: dict[str, str] = {}
    for field in preview.fields:
        value = sources.get(field.mapped_key, "")
        if not value:
            value = field.value
        if value:
            values[field.name] = value[:2000]
    return values


def inspect_delivery_profile(
    db: Session, company: Company, draft: OutreachDraft
) -> DeliveryProfileContext:
    profile, fields = _ready_profile(db, company)
    preview = inspect_form(
        profile.form_url,
        form_index=profile.form_index,
        profile_fields=fields,
        form_profile_id=profile.id,
        form_status=profile.form_status,
    )
    if preview.fingerprint != profile.fingerprint:
        profile.form_status = "STALE"
        db.commit()
        raise FormDeliveryError(
            "フォーム構造が解析時から変更されています。再解析してください。",
            "profile_changed",
        )
    values = mapped_values(preview, draft, db.get(FormSenderSettings, 1))
    preview = replace(
        preview,
        fields=[
            replace(field, value=values.get(field.name, field.value))
            for field in preview.fields
        ],
    )
    return DeliveryProfileContext(
        profile=profile,
        fields=fields,
        preview=preview,
        values=values,
    )


def required_missing(preview: FormPreview, values: dict[str, str]) -> list[str]:
    return [
        field.label
        for field in preview.fields
        if field.required and not values.get(field.name, "").strip()
    ]


def mapping_snapshot(fields: list[FormProfileField]) -> list[dict]:
    return [
        {
            "position": field.position,
            "name": field.name,
            "mapped_key": field.mapped_key,
            "confidence": field.confidence,
            "decision_source": field.decision_source,
            "recommended_value": field.recommended_value,
        }
        for field in fields
        if field.name
    ]


def mark_profile_changed(db: Session, profile: FormProfile, exc: FormDeliveryError) -> None:
    if exc.code == "profile_changed":
        profile.form_status = "STALE"
        db.commit()
