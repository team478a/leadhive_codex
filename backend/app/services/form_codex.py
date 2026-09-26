from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, FormProfileField, FormSenderSettings, OutreachDraft
from app.services.form_profile_delivery import primary_form_profile, sender_values

CODEX_FORM_SKILL = "leadhive-form-submit"
CODEX_FORM_INSTRUCTIONS = (
    "Codexで $leadhive-form-submit を使用してください。JSON内の送信承認、送信先、"
    "本文、送信者情報、解析済み項目を確認し、ブラウザで一件だけ処理します。"
    "CAPTCHAは回避せず利用者の操作を待ち、完了表示を確認できない場合は再送しません。"
)


@dataclass(frozen=True)
class CodexFormPayload:
    skill_name: str
    subject: str
    sender_values: dict[str, str]
    fields: list[dict]
    reason: str
    instructions: str


def _option_labels(options: list) -> list[str]:
    labels: list[str] = []
    for option in options:
        if isinstance(option, dict):
            label = str(option.get("label") or option.get("value") or "").strip()
        else:
            label = str(option).strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def build_codex_form_payload(
    db: Session,
    company: Company,
    draft: OutreachDraft,
    *,
    fallback_reason: str = "Codexによるブラウザ操作が必要です。",
) -> CodexFormPayload:
    profile = primary_form_profile(db, company.id)
    profile_fields = (
        list(
            db.scalars(
                select(FormProfileField)
                .where(FormProfileField.form_profile_id == profile.id)
                .order_by(FormProfileField.position)
            ).all()
        )
        if profile
        else []
    )
    senders = sender_values(db.get(FormSenderSettings, 1))
    sources = senders | {
        "subject": draft.subject.strip(),
        "message": draft.body.strip(),
    }
    fields: list[dict] = []
    for field in profile_fields:
        value = sources.get(field.mapped_key, "") or field.recommended_value.strip()
        fields.append(
            {
                "position": field.position,
                "label": field.label,
                "name": field.name,
                "field_type": field.field_type,
                "required": field.required,
                "mapped_key": field.mapped_key,
                "value": value[:2000],
                "options": _option_labels(field.options),
            }
        )
    reason = fallback_reason
    if profile:
        reason = profile.review_reason.strip() or fallback_reason
        if profile.captcha_type != "CAPTCHA_NONE":
            reason = f"{reason} CAPTCHA: {profile.captcha_type}".strip()
    return CodexFormPayload(
        skill_name=CODEX_FORM_SKILL,
        subject=draft.subject.strip(),
        sender_values={key: value for key, value in senders.items() if value},
        fields=fields,
        reason=reason,
        instructions=CODEX_FORM_INSTRUCTIONS,
    )
