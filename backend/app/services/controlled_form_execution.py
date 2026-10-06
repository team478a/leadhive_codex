"""Controlled-lab bridge only. No concrete transport, public API or worker registration."""

import json
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import settings
from app.models import (
    ApprovalRequest,
    Company,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    Project,
    ProjectMember,
)
from app.services import approved_form, approved_form_worker
from app.services.form_adapter_contract import ExecutableFormPlan, canonical_plan, digest
from app.services.form_adapter_preparation import enabled
from app.services.form_delivery import FormPreview
from app.services.form_delivery_result import FormSubmissionResult
from app.services.form_profile_delivery import DeliveryProfileContext, primary_form_profile
from app.services.form_submission_guard import UNKNOWN_MESSAGE


class ControlledTransport(Protocol):
    def observe(self, plan: ExecutableFormPlan) -> FormPreview: ...

    def post(self, plan: ExecutableFormPlan, attempt_id) -> FormSubmissionResult | None: ...


def ensure_enabled(db):
    if not (
        enabled()
        and settings.form_adapter_lab_execution_enabled
        and settings.outbound_enabled
        and settings.human_approved_form_enabled
        and db.scalar(select(func.current_database())).endswith("_test")
    ):
        raise HTTPException(409, "管理下実行は専用試験環境でのみ許可されます。")


def validate_context(db, item, row, context, plan):
    ensure_enabled(db)
    # Keep permissions and source inputs stable until UNKNOWN and consumption commit.
    db.scalar(select(Project).where(Project.id == item.project_id).with_for_update())
    db.scalar(select(Company).where(Company.id == item.company_id).with_for_update())
    db.scalars(
        select(ProjectMember)
        .where(
            ProjectMember.project_id == item.project_id,
            ProjectMember.user_id.in_({row.created_by_user_id, item.approved_by_user_id}),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    db.scalar(
        select(OutreachDraft).where(OutreachDraft.id == item.source_draft_id).with_for_update()
    )
    db.scalar(select(FormSenderSettings).where(FormSenderSettings.id == 1).with_for_update())
    db.scalar(select(FormProfile).where(FormProfile.id == plan.form_profile_id).with_for_update())
    db.scalars(
        select(FormProfileField)
        .where(
            FormProfileField.form_profile_id == plan.form_profile_id,
        )
        .with_for_update()
    ).all()
    if (
        item.delivery_method != "form_adapter"
        or canonical_plan(plan) != item.payload_snapshot.get("adapter_plan")
        or context.profile.id != plan.form_profile_id
        or context.preview.form_profile_id != plan.form_profile_id
        or context.preview.fingerprint != plan.field_fingerprint
        or context.profile.fingerprint != plan.field_fingerprint
        or context.preview.form_url != plan.form_url
        or context.preview.action_url != plan.steps[0].url
        or digest(
            {
                "form_url": context.preview.form_url,
                "action_url": context.preview.action_url,
                "method": "POST",
            }
        )
        != plan.route_fingerprint
        or context.values != item.payload_snapshot["field_values"]
    ):
        raise HTTPException(409, "承認済み計画と管理下フォームの観測が一致しません。")


def run(db, claimed, transport: ControlledTransport):
    row_id, worker_id = claimed.id, claimed.worker_id
    try:
        ensure_enabled(db)
        item = db.get(ApprovalRequest, claimed.approval_id)
        company, _ = approved_form.validate(db, item, allow_adapter=True)
        plan = ExecutableFormPlan.model_validate_json(
            json.dumps(item.payload_snapshot["adapter_plan"])
        )
        db.commit()  # Release locks before read-only lab observation.
        observed = transport.observe(plan)
        profile = primary_form_profile(db, company.id)
        fields = list(
            db.scalars(
                select(FormProfileField)
                .where(
                    FormProfileField.form_profile_id == profile.id,
                )
                .order_by(FormProfileField.position)
            ).all()
        )
        context = DeliveryProfileContext(
            profile, fields, observed, {v.name: v.value for v in plan.field_values}
        )
        row = approved_form_worker.begin(db, row_id, worker_id, context, adapter_plan=plan)
        if row is None:
            return
    except HTTPException as exc:
        approved_form_worker.block(db, row_id, worker_id, str(exc.detail))
        return
    except Exception:
        approved_form_worker.block(
            db, row_id, worker_id, "管理下フォームの事前確認を通過できません。"
        )
        return
    submission = None
    try:
        submission = transport.post(plan, row.delivery_id)  # Only after durable commit.
    except Exception:
        pass
    approved_form_worker.finish(
        db,
        row_id,
        worker_id,
        "submitted" if submission else "unknown",
        "" if submission else UNKNOWN_MESSAGE,
        submission,
    )
