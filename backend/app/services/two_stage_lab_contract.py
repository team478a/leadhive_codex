"""Separate synthetic two-stage binding; never a production dispatch contract."""

import re
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select

from app.models import FormProfileField, FormSenderSettings, OutreachDraft
from app.services.controlled_confirmation_review import guard
from app.services.form_adapter_contract import digest
from app.services.form_execution_plan import ExecutionPlan, FrozenContract, PlanStep
from app.services.form_profile_delivery import primary_form_profile, sender_values


class TwoStageLabPlan(FrozenContract):
    environment: Literal["CONTROLLED_LAB"] = "CONTROLLED_LAB"
    contract_version: Literal["two-stage-lab-v1"] = "two-stage-lab-v1"
    approval_id: UUID
    approval_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_draft_id: UUID
    form_profile_id: UUID
    source_draft_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    form_profile_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    sender_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    company_source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    execution_plan: ExecutionPlan

    @model_validator(mode="after")
    def two_posts_only(self):
        plan = self.execution_plan
        if plan.adapter_id != "fixture_js_confirmation" or plan.steps != (
            PlanStep(kind="confirm_post", url="https://fixture.example/confirm", method="POST"),
            PlanStep(kind="submit", url="https://fixture.example/submit", method="POST"),
        ):
            raise ValueError("Only the fixed synthetic two-stage protocol is supported")
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,99}", field.name)
            or field.name in {"fixture_token", "submitFinal"}
            for field in plan.field_values
        ):
            raise ValueError("Unsafe or reserved synthetic field name")
        return self


def canonical(plan: TwoStageLabPlan) -> dict:
    return TwoStageLabPlan.model_validate_json(plan.model_dump_json()).model_dump(mode="json")


def bind(db, request_id, session_id) -> TwoStageLabPlan:
    item, plan, _ = guard(db, request_id, session_id)
    profile = primary_form_profile(db, item.company_id)
    draft = db.get(OutreachDraft, item.source_draft_id) if item.source_draft_id else None
    sender = sender_values(db.get(FormSenderSettings, 1))
    fields = (
        db.scalars(
            select(FormProfileField).where(
                FormProfileField.form_profile_id == profile.id,
            )
        ).all()
        if profile
        else []
    )
    expected_sender = {
        "name": sender["contact_name"],
        "email": sender["email"],
        "company": sender["company_name"],
        "phone": sender["phone"],
    }
    sources = sender | {"subject": item.subject, "message": item.body}
    expected_fields = {
        field.name: sources.get(field.mapped_key, "") or field.recommended_value for field in fields
    }
    if (
        bool(item.payload_snapshot.get("attachment_metadata"))
        or not draft
        or draft.company_id != item.company_id
        or draft.channel != "form"
        or draft.subject != item.subject
        or draft.body != item.body
        or not profile
        or profile.form_url != plan.form_url
        or profile.action_url != plan.steps[0].url
        or profile.confirmation_page is not True
        or profile.fingerprint != plan.field_fingerprint
        or not fields
        or len(expected_fields) != len(fields)
        or any(field.field_type in {"file", "hidden", "submit", "button"} for field in fields)
        or any(field.required and not expected_fields[field.name].strip() for field in fields)
        or expected_fields != item.field_values
        or expected_sender != item.sender
        or plan.route_fingerprint
        != digest({"confirm": plan.steps[0].url, "submit": plan.steps[1].url})
    ):
        raise HTTPException(409, "承認済みDraft・送信者・二段階フォームの結合を確認できません。")
    # Every binding is already covered by the immutable Human-approved snapshot.
    return TwoStageLabPlan(
        approval_id=item.id,
        approval_hash=item.payload_hash,
        source_draft_id=draft.id,
        form_profile_id=profile.id,
        execution_plan=plan,
        **{
            key: item.payload_snapshot[key]
            for key in (
                "source_draft_hash",
                "form_profile_hash",
                "sender_source_hash",
                "company_source_hash",
            )
        },
    )


def validate_current(db, plan: TwoStageLabPlan, session_id):
    current = bind(db, plan.approval_id, session_id)
    if canonical(current) != canonical(plan):
        raise HTTPException(409, "管理用計画が変更されています。再準備・再承認してください。")
    return current
