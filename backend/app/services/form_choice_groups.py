"""Human group review ledger. Does not remove parser guards or authorize dispatch."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FormAnalysisLog, FormProfile, FormProfileField, User
from app.schema_core import Input
from app.services.form_intelligence.consent import CONSENT_KEYS
from app.services.form_intelligence.fields import GROUP_REVIEW_MARKER


class GroupSelection(Input):
    field_id: UUID
    value: str = Field(min_length=1, max_length=500)


class GroupReviewInput(Input):
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule: Literal["AT_LEAST_ONE", "EXACTLY_ONE"]
    selections: list[GroupSelection] = Field(min_length=1, max_length=50)
    membership_and_rule_confirmed: Literal[True]


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def grouped_fields(fields: list[FormProfileField]) -> dict[str, list[FormProfileField]]:
    groups: dict[str, list[FormProfileField]] = {}
    for field in fields:
        if GROUP_REVIEW_MARKER in field.label:
            # Stored headings are group candidates, not proof of DOM membership.
            key = digest(field.label)
            groups.setdefault(key, []).append(field)
    return groups


def source_hash(profile: FormProfile, fields: list[FormProfileField]) -> str:
    return digest(
        {
            "profile_id": str(profile.id),
            "fingerprint": profile.fingerprint,
            "fields": [
                {
                    "id": str(f.id),
                    "position": f.position,
                    "selector": f.selector,
                    "name": f.name,
                    "type": f.field_type,
                    "label": f.label,
                    "options": f.options,
                    "required": f.required,
                    "mapped_key": f.mapped_key,
                    "recommended_value": f.recommended_value,
                    "decision_source": f.decision_source,
                }
                for f in fields
            ],
        }
    )


def supported(fields: list[FormProfileField]) -> bool:
    return (
        1 < len(fields) <= 50
        and len({f.name for f in fields}) == len(fields)
        and all(
            f.name
            and f.field_type in {"checkbox", "radio"}
            and f.mapped_key not in CONSENT_KEYS
            and isinstance(f.options, list)
            and f.options
            and all(
                isinstance(o, dict)
                and isinstance(o.get("value"), str)
                and 0 < len(o["value"]) <= 500
                for o in f.options
            )
            and len({o["value"] for o in f.options}) == len(f.options)
            for f in fields
        )
    )


def inventory(db: Session, profile: FormProfile) -> list[dict]:
    fields = db.scalars(
        select(FormProfileField)
        .where(FormProfileField.form_profile_id == profile.id)
        .order_by(FormProfileField.position)
    ).all()
    logs = db.scalars(
        select(FormAnalysisLog)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.event_type == "manual_corrected",
            FormAnalysisLog.details["operation"].astext == "choice_group_review",
        )
        .order_by(FormAnalysisLog.created_at.desc(), FormAnalysisLog.id.desc())
    ).all()
    result = []
    now = datetime.now(timezone.utc)
    for group_id, members in grouped_fields(list(fields)).items():
        binding = source_hash(profile, members)
        latest = next((log for log in logs if log.details.get("group_id") == group_id), None)
        status = "NOT_REVIEWED"
        if latest:
            status = "RECORDED"
            if latest.details.get("source_hash_after") != binding:
                status = "STALE"
            elif datetime.fromisoformat(latest.details["expires_at"]) <= now:
                status = "EXPIRED"
        result.append(
            {
                "group_id": group_id,
                "label": members[0].label.replace(GROUP_REVIEW_MARKER, ""),
                "source_hash": binding,
                "review_supported": supported(members),
                "review_status": status,
                "execution_supported": False,
                "rule": latest.details.get("rule") if latest else None,
                "saved_selections": latest.details.get("selections", {}) if latest else {},
                "reviewed_at": latest.created_at if latest else None,
                "expires_at": latest.details.get("expires_at") if latest else None,
                "members": [
                    {"field_id": str(f.id), "name": f.name, "options": f.options} for f in members
                ],
            }
        )
    return result


def record_review(
    db: Session, profile: FormProfile, group_id: str, body: GroupReviewInput, user: User
) -> None:
    # Serialize group edits; no network, approval or delivery integration.
    db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    fields = list(
        db.scalars(
            select(FormProfileField)
            .where(FormProfileField.form_profile_id == profile.id)
            .order_by(FormProfileField.position)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    members = grouped_fields(fields).get(group_id)
    if not members:
        raise HTTPException(404, "必須グループが見つかりません。")
    if source_hash(profile, members) != body.expected_source_hash:
        raise HTTPException(
            409, "フォーム項目または選択値が変わりました。確認資料を読み直してください。"
        )
    if not supported(members) or len(profile.fingerprint) != 64:
        raise HTTPException(
            422, "このグループは安全に選択値を記録できません。元フォームを確認してください。"
        )
    selected = {item.field_id: item.value for item in body.selections}
    if len(selected) != len(body.selections) or not set(selected).issubset({f.id for f in members}):
        raise HTTPException(422, "同じ項目の重複またはグループ外の項目が含まれています。")
    if body.rule == "EXACTLY_ONE" and len(selected) != 1:
        raise HTTPException(422, "1項目だけ選択してください。")
    for field in members:
        if field.id in selected and selected[field.id] not in {o["value"] for o in field.options}:
            raise HTTPException(422, "選択値がフォームの選択肢と一致しません。")
        if field.required and field.id not in selected:
            raise HTTPException(422, "個別に必須の項目が未選択です。")
    before = {str(f.id): f.recommended_value for f in members}
    before_status = profile.form_status
    for field in members:
        field.recommended_value = selected.get(field.id, "")
        field.decision_source = "MANUAL"
        field.confidence = 1.0
    # Keep the marker and block native delivery even after Human records a rule.
    profile.form_status = (
        "BLOCKED"
        if (profile.form_status == "BLOCKED" or profile.sales_contact_status == "PROHIBITED")
        else "REVIEW_REQUIRED"
    )
    profile.review_reason = "必須グループの条件・選択を記録しました。自動送信経路は未対応です。"
    now = datetime.now(timezone.utc)
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            actor_user_id=user.id,
            created_at=now,
            event_type="manual_corrected",
            provider="manual",
            confidence=1.0,
            details={
                "operation": "choice_group_review",
                "group_id": group_id,
                "source_hash_before": body.expected_source_hash,
                "source_hash_after": source_hash(profile, members),
                "profile_fingerprint": profile.fingerprint,
                "rule": body.rule,
                "before": before,
                "selections": {str(k): v for k, v in selected.items()},
                "membership_and_rule_confirmed": True,
                "before_status": before_status,
                "after_status": profile.form_status,
                "expires_at": (now + timedelta(hours=24)).isoformat(),
                "send_authorized": False,
            },
        )
    )
    db.commit()
