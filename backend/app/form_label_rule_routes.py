from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, FormLabelRule, FormProfile, OperationJob, User
from app.project_access import project_access
from app.schema_core import Input
from app.schemas import OperationJobOut
from app.security import current_user
from app.services.form_intelligence.rules import STANDARD_KEYS, normalize_required_label
from app.services.form_label_rules import profile_ids_for_rule
from app.services.operations import add_operation_job

router = APIRouter(prefix="/api", tags=["Form label rules"])

FORBIDDEN_KEYS = {"privacy_consent", "newsletter_consent", "unknown"}
ALLOWED_KEYS = sorted(STANDARD_KEYS - FORBIDDEN_KEYS)


class FormLabelRuleInput(Input):
    normalized_label: str = Field(min_length=1, max_length=500)
    field_type: str = Field(min_length=1, max_length=50)
    mapped_key: str = Field(min_length=1, max_length=50)
    recommended_value: str = Field(default="", max_length=500)


def _active_job(db: Session, project_id: UUID) -> OperationJob | None:
    return db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_label_rule",
            OperationJob.status.in_(("queued", "running")),
        )
        .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
        .limit(1)
    )


def _rule_out(rule: FormLabelRule) -> dict:
    return {
        "id": rule.id,
        "project_id": rule.project_id,
        "normalized_label": rule.normalized_label,
        "field_type": rule.field_type,
        "mapped_key": rule.mapped_key,
        "recommended_value": rule.recommended_value,
        "status": rule.status,
        "created_by_user_id": rule.created_by_user_id,
        "created_at": rule.created_at,
        "retired_at": rule.retired_at,
    }


def _enqueue(db: Session, rule: FormLabelRule, action: Literal["apply", "reset"], user: User):
    if _active_job(db, rule.project_id) is not None:
        raise HTTPException(409, "項目名ルールの処理がすでに実行中です。")
    job = OperationJob(
        project_id=rule.project_id,
        operation_type="form_label_rule",
        payload={"action": action, "rule_id": str(rule.id), "requested_by_user_id": str(user.id)},
    )
    if not add_operation_job(db, job):
        raise HTTPException(409, "項目名ルールの処理がすでに実行中です。")
    return job


@router.get("/projects/{project_id}/form-label-rules")
def list_form_label_rules(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    rules = db.scalars(
        select(FormLabelRule)
        .where(FormLabelRule.project_id == project_id)
        .order_by(FormLabelRule.created_at.desc(), FormLabelRule.id.desc())
    ).all()
    active_job = _active_job(db, project_id)
    return {
        "rules": [_rule_out(rule) for rule in rules],
        "active_job": OperationJobOut.model_validate(active_job) if active_job else None,
        "allowed_mapped_keys": ALLOWED_KEYS,
    }


@router.get("/projects/{project_id}/form-label-rules/preview")
def preview_form_label_rule(
    project_id: UUID,
    normalized_label: str = Query(min_length=1, max_length=500),
    field_type: str = Query(min_length=1, max_length=50),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    probe = FormLabelRule(
        project_id=project_id,
        normalized_label=normalize_required_label(normalized_label),
        field_type=field_type,
        mapped_key="other",
        created_by_user_id=user.id,
    )
    profile_ids = profile_ids_for_rule(db, probe)
    examples = db.execute(
        select(Company.company_name, FormProfile.form_url)
        .join(FormProfile, FormProfile.company_id == Company.id)
        .where(FormProfile.id.in_(profile_ids))
        .order_by(Company.company_name, FormProfile.form_url)
        .limit(5)
    ).all()
    return {
        "form_count": len(profile_ids),
        "examples": [
            {"company_name": company_name, "form_url": form_url}
            for company_name, form_url in examples
        ],
    }


@router.post("/projects/{project_id}/form-label-rules", status_code=202)
def create_form_label_rule(
    project_id: UUID,
    body: FormLabelRuleInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=True)
    if body.mapped_key not in ALLOWED_KEYS:
        raise HTTPException(422, "この対応先は項目名ルールでは使用できません。")
    if body.mapped_key == "message" and body.field_type != "textarea":
        raise HTTPException(422, "問い合わせ本文はtextareaの項目名ルールだけに設定できます。")
    if body.mapped_key == "email" and body.field_type not in {"email", "text"}:
        raise HTTPException(
            422, "メールアドレスはemailまたはtextの項目名ルールだけに設定できます。"
        )
    if body.recommended_value and body.field_type not in {"select", "radio"}:
        raise HTTPException(422, "既定の選択値はselectまたはradioだけに設定できます。")
    rule = FormLabelRule(
        project_id=project_id,
        normalized_label=normalize_required_label(body.normalized_label),
        field_type=body.field_type,
        mapped_key=body.mapped_key,
        recommended_value=body.recommended_value,
        created_by_user_id=user.id,
    )
    db.add(rule)
    try:
        db.flush()
        job = _enqueue(db, rule, "apply", user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "同じ項目名と型の有効なルールがすでにあります。") from exc
    db.refresh(rule)
    db.refresh(job)
    return {"rule": _rule_out(rule), "job": OperationJobOut.model_validate(job)}


@router.post("/projects/{project_id}/form-label-rules/{rule_id}/retire")
def retire_form_label_rule(
    project_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=True)
    rule = db.get(FormLabelRule, rule_id)
    if rule is None or rule.project_id != project_id:
        raise HTTPException(404, "項目名ルールが見つかりません。")
    if rule.status == "ACTIVE":
        rule.status = "RETIRED"
        rule.retired_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(rule)
    return _rule_out(rule)


@router.post("/projects/{project_id}/form-label-rules/{rule_id}/reset", status_code=202)
def reset_form_label_rule(
    project_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=True)
    rule = db.get(FormLabelRule, rule_id)
    if rule is None or rule.project_id != project_id:
        raise HTTPException(404, "項目名ルールが見つかりません。")
    job = _enqueue(db, rule, "reset", user)
    db.commit()
    db.refresh(job)
    return {"rule": _rule_out(rule), "job": OperationJobOut.model_validate(job)}
