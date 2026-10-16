"""Human form review queue; records review evidence but never sends or approves."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.form_dm_readiness_routes import _rows, classify_profile
from app.models import (
    Company,
    FormAnalysisLog,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    User,
)
from app.project_access import company_access, project_access
from app.schema_core import Input
from app.schema_form_intelligence import MappedKey
from app.security import current_user
from app.services.form_choice_groups import (
    grouped_fields,
)
from app.services.form_choice_groups import (
    source_hash as choice_group_hash,
)
from app.services.form_choice_groups import (
    supported as choice_group_supported,
)
from app.services.form_intelligence.consent import CONSENT_KEYS
from app.services.form_intelligence.fields import GROUP_REVIEW_MARKER, mapping_review_reason
from app.services.form_profile_delivery import sender_values
from app.services.form_review_binding import field_material as _field_material
from app.services.form_review_binding import fields_hash as _fields_hash
from app.services.form_saved_choice_reviews import (
    material as saved_choice_material,
)
from app.services.form_saved_choice_reviews import (
    reviewable as saved_choice_reviewable,
)

router = APIRouter(prefix="/api", tags=["Form review queue"])
PAGE_SIZE = 20
REVIEW_REASONS = {
    "NEEDS_CONSENT_REVIEW",
    "NEEDS_CHOICE_REVIEW",
    "NEEDS_MAPPING_REVIEW",
}
BLOCKING_REASONS = {
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
}


class FieldDecision(Input):
    field_id: UUID
    mapped_key: MappedKey
    recommended_value: str = Field(default="", max_length=500)
    consent_checked: StrictBool = False


class GroupSelection(Input):
    field_id: UUID
    value: str = Field(min_length=1, max_length=500)


class GroupDecision(Input):
    group_id: str = Field(min_length=1, max_length=64)
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule: Literal["AT_LEAST_ONE", "EXACTLY_ONE"]
    selections: list[GroupSelection] = Field(min_length=1, max_length=50)


class SavedOptionDecision(Input):
    option_id: str = Field(max_length=100)
    checked: StrictBool


class SavedGroupDecision(Input):
    group_id: str = Field(min_length=1, max_length=100)
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule: Literal["OPTIONAL", "AT_LEAST_ONE", "EXACTLY_ONE"]
    options: list[SavedOptionDecision] = Field(min_length=1, max_length=100)


class FormReviewDecision(Input):
    action: Literal["CONFIRM", "DO_NOT_SEND"]
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_fields_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_no_sales_prohibition: Literal[True]
    field_decisions: list[FieldDecision] = Field(default_factory=list, max_length=100)
    group_decisions: list[GroupDecision] = Field(default_factory=list, max_length=50)
    saved_group_decisions: list[SavedGroupDecision] = Field(default_factory=list, max_length=50)
    do_not_send_reason: Literal["SALES_PROHIBITED", "WRONG_PURPOSE", "OTHER"] | None = None
    do_not_send_note: str = Field(default="", max_length=500)


def _field_rows(db: Session, profile_id: UUID, *, lock: bool = False) -> list[FormProfileField]:
    query = (
        select(FormProfileField)
        .where(FormProfileField.form_profile_id == profile_id)
        .order_by(FormProfileField.position, FormProfileField.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(query).all())


def _current_review_log(db: Session, profile: FormProfile, fields: list[FormProfileField]):
    logs = db.scalars(
        select(FormAnalysisLog)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
        )
        .order_by(FormAnalysisLog.created_at.desc(), FormAnalysisLog.id.desc())
    ).all()
    current_hash = _fields_hash(profile, fields)
    return next(
        (
            log
            for log in logs
            if log.details.get("profile_fingerprint") == profile.fingerprint
            and log.details.get("fields_hash") == current_hash
        ),
        None,
    )


def _display_value(mapped_key: str, choices: dict[str, str], draft: OutreachDraft | None) -> str:
    if mapped_key == "subject":
        return draft.subject if draft else ""
    if mapped_key == "message":
        return draft.body if draft else ""
    return choices.get(mapped_key, "")


def _queue_item(db: Session, company: Company, profile: FormProfile, reasons: list[str]) -> dict:
    fields = _field_rows(db, profile.id)
    draft = db.scalar(
        select(OutreachDraft)
        .where(OutreachDraft.company_id == company.id, OutreachDraft.channel == "form")
        .order_by(OutreachDraft.updated_at.desc(), OutreachDraft.id.desc())
        .limit(1)
    )
    choices = sender_values(db.get(FormSenderSettings, 1))
    output_fields = []
    for field in fields:
        row = _field_material(field)
        row["display_value"] = (
            ""
            if field.mapped_key in CONSENT_KEYS
            else field.recommended_value or _display_value(field.mapped_key, choices, draft)
        )
        output_fields.append(row)
    groups = []
    for group_id, members in grouped_fields(fields).items():
        groups.append(
            {
                "group_id": group_id,
                "source_hash": choice_group_hash(profile, members),
                "label": members[0].label.replace(GROUP_REVIEW_MARKER, ""),
                "supported": choice_group_supported(members),
                "members": [
                    {
                        "field_id": str(field.id),
                        "label": field.label,
                        "required": field.required,
                        "options": field.options,
                    }
                    for field in members
                ],
            }
        )
    saved_groups = [
        group | {"reviewable": saved_choice_reviewable(group, profile)}
        for group in saved_choice_material(db, profile)["groups"]
    ]
    return {
        "company_id": str(company.id),
        "company_name": company.company_name,
        "profile_id": str(profile.id),
        "form_url": profile.form_url,
        "fingerprint": profile.fingerprint,
        "fields_hash": _fields_hash(profile, fields),
        "reason_codes": reasons,
        "fields": output_fields,
        "groups": groups,
        "saved_groups": saved_groups,
    }


@router.get("/projects/{project_id}/form-review-queue")
def get_form_review_queue(
    project_id: UUID,
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    items = []
    for company, profile in _rows(db, project_id):
        if profile.is_primary is not True or len(profile.fingerprint or "") != 64:
            continue
        result = classify_profile(db, company, profile)
        codes = [result["primary_reason"], *result["secondary_reasons"]]
        if not REVIEW_REASONS.intersection(codes) or BLOCKING_REASONS.intersection(codes):
            continue
        fields = _field_rows(db, profile.id)
        if _current_review_log(db, profile, fields):
            continue
        items.append(_queue_item(db, company, profile, codes))
    return {
        "total": len(items),
        "offset": offset,
        "limit": PAGE_SIZE,
        "items": items[offset : offset + PAGE_SIZE],
        "read_only": True,
        "external_requests": 0,
    }


def _validate_choice_value(field: FormProfileField, value: str) -> None:
    if not value:
        return
    options = field.options if isinstance(field.options, list) else []
    if options and value not in {
        str(item.get("value") or "") for item in options if isinstance(item, dict)
    }:
        raise HTTPException(422, "保存する値がフォームの選択肢にありません。")


@router.post("/form-profiles/{profile_id}/review-decision")
def save_form_review_decision(
    profile_id: UUID,
    body: FormReviewDecision,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    profile = db.get(FormProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "フォームが見つかりません。")
    company = company_access(profile.company_id, db, user)
    profile = db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert profile is not None
    if profile.form_found is not True or not profile.is_primary:
        raise HTTPException(409, "主フォームではありません。キューを再読み込みしてください。")
    if profile.fingerprint != body.expected_fingerprint:
        raise HTTPException(409, "フォーム構造が変更されています。確認し直してください。")
    if profile.form_status in {"STALE", "ERROR", "BLOCKED"}:
        raise HTTPException(409, "フォームの最新状態を確認できません。再解析してください。")
    fields = _field_rows(db, profile.id, lock=True)
    if _fields_hash(profile, fields) != body.expected_fields_hash:
        raise HTTPException(409, "入力項目が変更されています。キューを再読み込みしてください。")
    if company.do_not_contact or profile.sales_contact_status == "PROHIBITED":
        raise HTTPException(409, "連絡禁止または営業禁止のフォームは確認キューで変更できません。")
    if body.action == "DO_NOT_SEND":
        if not body.do_not_send_reason:
            raise HTTPException(422, "送信しない理由を選択してください。")
        reason_labels = {
            "SALES_PROHIBITED": "営業お断り",
            "WRONG_PURPOSE": "用途違い",
            "OTHER": "その他",
        }
        note = body.do_not_send_note.strip()
        company.do_not_contact = True
        company.exclusion_reason = f"フォーム確認: {reason_labels[body.do_not_send_reason]}" + (
            f" ({note})" if note else ""
        )
        db.add(
            FormAnalysisLog(
                company_id=company.id,
                form_profile_id=profile.id,
                actor_user_id=user.id,
                event_type="manual_corrected",
                provider="manual",
                details={
                    "operation": "form_review_do_not_send",
                    "reason": body.do_not_send_reason,
                    "note": note,
                    "profile_fingerprint": profile.fingerprint,
                    "fields_hash": body.expected_fields_hash,
                    "send_authorized": False,
                },
            )
        )
        db.commit()
        return {"status": "DO_NOT_SEND", "company_id": str(company.id)}

    if body.do_not_send_reason is not None:
        raise HTTPException(422, "確認内容が不正です。")
    if profile.sales_contact_status != "ALLOWED" or profile.captcha_type != "CAPTCHA_NONE":
        raise HTTPException(409, "営業可否またはCAPTCHAを安全に確認できないフォームです。")
    if not profile.delivery_supported or profile.confirmation_page is not False:
        raise HTTPException(409, "このフォームは本確認キューの対象外です。")
    by_id = {field.id: field for field in fields}
    decisions = {item.field_id: item for item in body.field_decisions}
    if len(decisions) != len(body.field_decisions) or set(decisions) != set(by_id):
        raise HTTPException(422, "全項目を確認する必要があります。")
    original_groups = grouped_fields(fields)
    group_decisions = {item.group_id: item for item in body.group_decisions}
    if len(group_decisions) != len(body.group_decisions) or set(group_decisions) != set(
        original_groups
    ):
        if original_groups or body.group_decisions:
            raise HTTPException(422, "同名チェック項目の確認をすべて行ってください。")
    for group_id, members in original_groups.items():
        decision = group_decisions[group_id]
        if not choice_group_supported(members):
            raise HTTPException(422, "同名チェック項目の構造を安全に確認できません。")
        if choice_group_hash(profile, members) != decision.expected_source_hash:
            raise HTTPException(409, "同名チェック項目が変更されています。読み直してください。")
    saved_before = saved_choice_material(db, profile)["groups"]
    if any(not saved_choice_reviewable(group, profile) for group in saved_before):
        raise HTTPException(422, "安全に確認できない保存済み選択肢があるため確定できません。")
    saved_decisions = {item.group_id: item for item in body.saved_group_decisions}
    required_saved = {g["group_id"] for g in saved_before if saved_choice_reviewable(g, profile)}
    if (
        len(saved_decisions) != len(body.saved_group_decisions)
        or set(saved_decisions) != required_saved
    ):
        if required_saved or body.saved_group_decisions:
            raise HTTPException(422, "保存済み選択肢の確認が不足しています。")
    for group in saved_before:
        if group["group_id"] not in required_saved:
            continue
        decision = saved_decisions[group["group_id"]]
        if decision.expected_source_hash != group["source_hash"]:
            raise HTTPException(409, "保存済み選択肢が変更されています。読み直してください。")
        received = {item.option_id: item.checked for item in decision.options}
        if len(received) != len(decision.options) or set(received) != {
            o["option_id"] for o in group["options"]
        }:
            raise HTTPException(422, "保存済み選択肢をすべて確認してください。")
        count = sum(received.values())
        if (
            (decision.rule == "EXACTLY_ONE" and count != 1)
            or (decision.rule == "AT_LEAST_ONE" and count < 1)
            or (decision.rule == "OPTIONAL" and group["required_observed"])
        ):
            raise HTTPException(422, "選択条件が選択結果と一致しません。")
    for field in fields:
        decision = decisions[field.id]
        if decision.mapped_key == "newsletter_consent":
            if decision.consent_checked or decision.recommended_value:
                raise HTTPException(422, "メルマガ登録は常に未選択にしてください。")
            field.recommended_value = ""
        elif decision.mapped_key == "privacy_consent":
            if field.field_type != "checkbox" or len(field.options or []) != 1:
                raise HTTPException(422, "同意チェック項目を安全に確認できません。")
            option_value = str((field.options[0] or {}).get("value") or "")
            if decision.consent_checked and not option_value:
                raise HTTPException(422, "同意の選択値を確認できません。")
            if field.required and not decision.consent_checked:
                raise HTTPException(422, "必須の同意は人がチェックしてから確定してください。")
            field.recommended_value = option_value if decision.consent_checked else ""
        else:
            if decision.consent_checked:
                raise HTTPException(422, "同意以外の項目に同意チェックは指定できません。")
            _validate_choice_value(field, decision.recommended_value)
            field.recommended_value = decision.recommended_value
        field.mapped_key = decision.mapped_key
        field.confidence = 1.0
        field.decision_source = "MANUAL"
    existing_groups = grouped_fields(fields)
    before_status = profile.form_status
    for group_id, members in existing_groups.items():
        decision = group_decisions[group_id]
        if not choice_group_supported(members):
            raise HTTPException(422, "同名チェック項目の構造を安全に確認できません。")
        selected = {item.field_id: item.value for item in decision.selections}
        if len(selected) != len(decision.selections) or not set(selected).issubset(
            {field.id for field in members}
        ):
            raise HTTPException(422, "選択値に重複またはグループ外の項目があります。")
        if decision.rule == "EXACTLY_ONE" and len(selected) != 1:
            raise HTTPException(422, "ちょうど1項目を選択してください。")
        for field in members:
            options = {
                str(item.get("value") or "") for item in field.options if isinstance(item, dict)
            }
            if field.id in selected and selected[field.id] not in options:
                raise HTTPException(422, "選択値が項目の保存済み選択肢と一致しません。")
            if field.required and field.id not in selected:
                raise HTTPException(422, "個別に必須の選択項目が未選択です。")
            field.recommended_value = selected.get(field.id, "")
            field.confidence = 1.0
            field.decision_source = "MANUAL"
    fields_for_mapping = []
    for field in fields:
        values = _field_material(field)
        if any(field.id in members for members in existing_groups.values()):
            values["label"] = values["label"].replace(GROUP_REVIEW_MARKER, "")
        fields_for_mapping.append(values)
    mapping_reason = mapping_review_reason(fields_for_mapping)
    if mapping_reason:
        raise HTTPException(422, f"確認が不足しています: {mapping_reason}")
    profile.form_status = "READY"
    profile.review_reason = ""
    db.flush()
    after_fields = _field_rows(db, profile.id, lock=True)
    choice_group_hashes = {
        group_id: choice_group_hash(profile, grouped_fields(after_fields)[group_id])
        for group_id in existing_groups
    }
    current_saved_groups = {
        group["group_id"]: group for group in saved_choice_material(db, profile)["groups"]
    }
    saved_choice_reviews = []
    for group_id in sorted(required_saved):
        current_group = current_saved_groups.get(group_id)
        if current_group is None or not saved_choice_reviewable(current_group, profile):
            raise HTTPException(409, "保存済み選択肢が更新されました。読み直してください。")
        saved_choice_reviews.append(
            {
                "group_id": group_id,
                "source_hash": current_group["source_hash"],
                "options": [item.model_dump() for item in saved_decisions[group_id].options],
                "rule": saved_decisions[group_id].rule,
            }
        )
    now = datetime.now(timezone.utc)
    db.add(
        FormAnalysisLog(
            company_id=company.id,
            form_profile_id=profile.id,
            actor_user_id=user.id,
            created_at=now,
            event_type="manual_corrected",
            provider="manual",
            confidence=1.0,
            details={
                "operation": "form_review_confirmed",
                "profile_fingerprint": profile.fingerprint,
                "fields_hash": _fields_hash(profile, after_fields),
                "confirmed_no_sales_prohibition": True,
                "choice_group_source_hashes": choice_group_hashes,
                "choice_group_rules": {
                    group_id: group_decisions[group_id].rule for group_id in group_decisions
                },
                "choice_group_selections": {
                    group_id: {
                        str(selection.field_id): selection.value
                        for selection in group_decisions[group_id].selections
                    }
                    for group_id in group_decisions
                },
                "saved_choice_reviews": saved_choice_reviews,
                "confirmed_at": now.isoformat(),
                "before_status": before_status,
                "after_status": profile.form_status,
                "send_authorized": False,
                "execution_allowed": False,
            },
        )
    )
    db.commit()
    return {"status": "CONFIRMED", "company_id": str(company.id), "profile_id": str(profile.id)}
