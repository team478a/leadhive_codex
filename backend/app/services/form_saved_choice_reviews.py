"""Non-executable Human option review, stored in the existing analysis ledger."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FormAnalysisLog, FormProfile, FormProfileField, User
from app.schema_core import Input
from app.schemas import FormProfileFieldOut
from app.services.form_saved_choice_structure import inventory

OPERATION = "saved_choice_review"


class OptionReview(Input):
    option_id: str = Field(max_length=100)
    checked: StrictBool


class SavedChoiceReviewInput(Input):
    expected_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule: Literal["OPTIONAL", "AT_LEAST_ONE", "EXACTLY_ONE"]
    options: list[OptionReview] = Field(min_length=1, max_length=100)
    membership_and_rule_confirmed: Literal[True]
    non_consent_purpose_confirmed: Literal[True]


def material(db: Session, profile: FormProfile, *, lock: bool = False) -> dict:
    query = (
        select(FormProfileField)
        .where(FormProfileField.form_profile_id == profile.id)
        .order_by(FormProfileField.position, FormProfileField.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    fields = db.scalars(query).all()
    return inventory(
        [FormProfileFieldOut.model_validate(f).model_dump() for f in fields],
        profile.fingerprint,
    )


def reviewable(group: dict, profile: FormProfile) -> bool:
    return (
        profile.form_status not in {"STALE", "ERROR"}
        and len(profile.fingerprint) == 64
        and len(group["options"]) <= 100
        and not set(group["warnings"]).intersection(
            {
                "FIELD_IDENTITY_UNCERTAIN",
                "INCOMPLETE_OPTIONS",
                "AMBIGUOUS_VALUES",
                "CONSENT_REVIEW_REQUIRED",
            }
        )
        and all(len(o["value"]) <= 500 for o in group["options"])
    )


def reviews(db: Session, profile: FormProfile) -> list[dict]:
    logs = db.scalars(
        select(FormAnalysisLog)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == OPERATION,
        )
        .order_by(FormAnalysisLog.created_at.desc(), FormAnalysisLog.id.desc())
    ).all()
    result = []
    for group in material(db, profile)["groups"]:
        latest = next(
            (log for log in logs if log.details.get("group_id") == group["group_id"]), None
        )
        status = "NOT_REVIEWED"
        if latest:
            status = "RECORDED"
            if latest.details["source_hash"] != group["source_hash"] or profile.form_status in {
                "STALE",
                "ERROR",
            }:
                status = "STALE"
            elif datetime.fromisoformat(latest.details["expires_at"]) <= datetime.now(timezone.utc):
                status = "EXPIRED"
        result.append(
            group
            | {
                "review_supported": reviewable(group, profile),
                "review_status": status,
                "reviewed_at": latest.created_at if latest else None,
                "reviewed_by": str(latest.actor_user_id) if latest else None,
                "expires_at": latest.details["expires_at"] if latest else None,
                "recorded_rule": latest.details["rule"] if latest else None,
                # Stale/expired values are historical only, never active selections.
                "recorded_options": latest.details["options"] if latest else [],
            }
        )
    return result


def record(
    db: Session, profile: FormProfile, group_id: str, body: SavedChoiceReviewInput, user: User
) -> None:
    db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    group = next(
        (g for g in material(db, profile, lock=True)["groups"] if g["group_id"] == group_id), None
    )
    if group is None:
        raise HTTPException(404, "確認対象が見つかりません。")
    if body.expected_source_hash != group["source_hash"]:
        raise HTTPException(409, "項目が変更されています。読み直して再確認してください。")
    if not reviewable(group, profile):
        raise HTTPException(422, "項目・同意・選択値を安全に記録できません。")
    received = {o.option_id: o.checked for o in body.options}
    if len(received) != len(body.options) or set(received) != {
        o["option_id"] for o in group["options"]
    }:
        raise HTTPException(422, "全選択肢の選択・未選択を重複なく確認してください。")
    count = sum(received.values())
    if (
        (body.rule == "EXACTLY_ONE" and count != 1)
        or (body.rule == "AT_LEAST_ONE" and count < 1)
        or (body.rule == "OPTIONAL" and group["required_observed"])
    ):
        raise HTTPException(422, "確認した選択条件に一致しません。")
    now = datetime.now(timezone.utc)
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            actor_user_id=user.id,
            created_at=now,
            event_type="manual_corrected",
            provider="manual",
            details={
                "operation": OPERATION,
                "group_id": group_id,
                "source_hash": group["source_hash"],
                "profile_fingerprint": profile.fingerprint,
                "rule": body.rule,
                "options": [o | {"checked": received[o["option_id"]]} for o in group["options"]],
                "expires_at": (now + timedelta(hours=24)).isoformat(),
                "membership_and_rule_confirmed": True,
                "non_consent_purpose_confirmed": True,
                "before_status": profile.form_status,
                "after_status": profile.form_status,
                "send_authorized": False,
                "execution_allowed": False,
            },
        )
    )
    # No field values/statuses, permissions, drafts, approvals or deliveries change.
    db.commit()
