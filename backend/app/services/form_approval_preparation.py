"""Prepare immutable proposals from stored data only; never fetch or submit a form."""

from fastapi import HTTPException
from pydantic import ValidationError

from app.models import FormSenderSettings
from app.schema_approval import Proposal
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_delivery import FormDeliveryError
from app.services.form_profile_delivery import _ready_profile, sender_values
from app.services.human_approval import (
    company_fingerprint,
    draft_fingerprint,
    form_dependency_hash,
    form_sender_hash,
    payload_hash,
)


def preparation(db, company, draft):
    if draft.channel != "form":
        raise HTTPException(409, "フォーム用Draftを選択してください。")
    try:
        profile, fields = _ready_profile(db, company)
    except FormDeliveryError as exc:
        raise HTTPException(409, exc.public_message) from exc
    if not profile.form_found or not profile.fingerprint:
        raise HTTPException(409, "フォーム構造が未確定です。再解析してください。")
    if not profile.action_url:
        raise HTTPException(409, "フォームのPOST先が未確定です。再解析してください。")
    decision = evaluate_contact_permission(
        db, company.project_id, company.id, "form", profile.form_url
    )
    if not decision.allowed:
        raise HTTPException(409, decision.message)
    sources = sender_values(db.get(FormSenderSettings, 1))
    values = sources | {"subject": draft.subject, "message": draft.body}
    visible = [
        f for f in fields if f.name and f.field_type not in {"hidden", "submit", "button", "reset"}
    ]
    if not visible or any(f.field_type == "file" for f in visible):
        raise HTTPException(
            409, "入力項目が未確定、または添付ファイルが必要です。人間による確認が必要です。"
        )
    names = [f.name for f in visible]
    if len(names) != len(set(names)):
        raise HTTPException(409, "同名の入力項目があります。人間による確認が必要です。")
    field_values = {f.name: values.get(f.mapped_key, "") or f.recommended_value for f in visible}
    if any(f.required and not field_values[f.name].strip() for f in visible):
        raise HTTPException(
            409, "必須項目が不足しています。送信者設定・Draft・フォーム解析を確認してください。"
        )
    if not any(f.mapped_key == "message" for f in visible):
        raise HTTPException(409, "本文の入力項目を確認してください。")
    try:
        proposal = Proposal(
            company_id=company.id,
            channel="form",
            delivery_method="form_direct",
            source_draft_id=draft.id,
            form_url=profile.form_url,
            form_action_url=profile.action_url or None,
            subject=draft.subject,
            body=draft.body,
            sender={
                "name": sources.get("contact_name", ""),
                "email": sources.get("email", ""),
                "company": sources.get("company_name", ""),
                "phone": sources.get("phone", ""),
            },
            field_values=field_values,
        )
    except ValidationError as exc:
        raise HTTPException(
            409, "送信者名・メールアドレス・文面・入力値を確認してください。"
        ) from exc
    digest = payload_hash(
        {
            "proposal": proposal.model_dump(mode="json"),
            "company": company_fingerprint(company),
            "draft": draft_fingerprint(draft),
            "form": form_dependency_hash(db, company.id),
            "sender": form_sender_hash(db),
        }
    )
    return proposal, {
        "preparation_hash": digest,
        "company_name": company.company_name,
        "form_profile_id": str(profile.id),
        "form_fingerprint": profile.fingerprint,
        "proposal": proposal.model_dump(mode="json"),
        "fields": [
            {
                "name": f.name,
                "label": f.label or f.name,
                "required": f.required,
                "value": field_values[f.name],
            }
            for f in visible
        ],
    }
