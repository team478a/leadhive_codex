"""Stored-data controlled-lab preparation. No execution or external observation."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.engine import make_url

from app.config import settings
from app.schema_approval import Proposal
from app.services.form_adapter_contract import (
    CONTACT,
    SUBMIT,
    ExecutableFormPlan,
    adapter_plan_hash,
    digest,
)
from app.services.form_approval_preparation import preparation
from app.services.form_execution_plan import InputValue, PlanStep


def enabled():
    return settings.form_adapter_preparation_enabled and (
        make_url(settings.database_url).database or ""
    ).endswith("_test")


def ensure_enabled():
    if not enabled():
        raise HTTPException(409, "管理下フォームの準備は専用試験環境だけで有効にできます。")


def adapter_preparation(db, company, draft):
    ensure_enabled()
    base, preview = preparation(db, company, draft)
    if str(base.form_url) != CONTACT or str(base.form_action_url) != SUBMIT:
        raise HTTPException(409, "この工程では管理下の固定フォームだけを準備できます。")
    try:
        plan = ExecutableFormPlan(
            environment="CONTROLLED_LAB",
            adapter_id="controlled_lab_single_post",
            adapter_version="1",
            project_id=company.project_id,
            company_id=company.id,
            source_draft_id=draft.id,
            form_profile_id=UUID(preview["form_profile_id"]),
            form_id=preview["form_profile_id"],
            form_url=CONTACT,
            field_fingerprint=preview["form_fingerprint"],
            route_fingerprint=digest({"form_url": CONTACT, "action_url": SUBMIT, "method": "POST"}),
            payload_version=1,
            sender=tuple(InputValue(name=k, value=v) for k, v in base.sender.model_dump().items()),
            subject=base.subject,
            body=base.body,
            field_values=tuple(InputValue(name=k, value=v) for k, v in base.field_values.items()),
            steps=(PlanStep(kind="submit", url=SUBMIT, method="POST"),),
        )
        data = base.model_dump(mode="json") | {
            "delivery_method": "form_adapter",
            "adapter_plan": plan.model_dump(mode="json"),
        }
        proposal = Proposal.model_validate(data)
    except ValueError as exc:
        raise HTTPException(
            409, "保存済みの構造・入力値・文面が操作計画の条件に合いません。"
        ) from exc
    return proposal, preview | {
        "proposal": proposal.model_dump(mode="json"),
        "adapter_plan_hash": adapter_plan_hash(plan),
        "reservation_only": True,
        "preparation_hash": digest(
            {
                "stored_preparation_hash": preview["preparation_hash"],
                "adapter_plan_hash": adapter_plan_hash(plan),
            }
        ),
    }
