from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    FormAnalysisLog,
    FormLabelRule,
    FormProfile,
    FormProfileField,
    OperationJob,
)
from app.services.form_intelligence.consent import CONSENT_KEYS
from app.services.form_intelligence.profile_status import recompute_stored_profile_status
from app.services.form_intelligence.rules import normalize_required_label
from app.services.operations import add_operation_job

TECHNICAL_FIELD_TYPES = {"hidden", "submit", "button", "reset", "image"}


def _source_label(field: FormProfileField) -> str:
    return (field.label or field.name or "").strip()


def unresolved_for_rule(field: FormProfileField, rule: FormLabelRule) -> bool:
    return (
        field.required
        and field.field_type not in TECHNICAL_FIELD_TYPES
        and field.field_type == rule.field_type
        and field.decision_source not in {"MANUAL", "POLICY"}
        and field.mapped_key not in CONSENT_KEYS
        and (field.mapped_key == "unknown" or field.confidence < 0.8)
        and normalize_required_label(_source_label(field)) == rule.normalized_label
    )


def _option_value_exists(field: FormProfileField, value: str) -> bool:
    if not value:
        return True
    if field.field_type not in {"select", "radio"}:
        return False
    return any(str(option.get("value") or "") == value for option in (field.options or []))


def apply_rule_to_profile(db: Session, rule: FormLabelRule, profile: FormProfile) -> int:
    if rule.status != "ACTIVE":
        return 0
    fields = list(
        db.scalars(
            select(FormProfileField)
            .where(FormProfileField.form_profile_id == profile.id)
            .order_by(FormProfileField.position, FormProfileField.id)
        ).all()
    )
    targets = [field for field in fields if unresolved_for_rule(field, rule)]
    if not targets:
        return 0
    target_ids = {field.id for field in targets}
    duplicates = [
        field
        for field in fields
        if field.id not in target_ids and field.mapped_key == rule.mapped_key
    ]
    if len(targets) != 1 or duplicates:
        return 0
    field = targets[0]
    if rule.recommended_value and not _option_value_exists(field, rule.recommended_value):
        return 0
    field.mapped_key = rule.mapped_key
    field.confidence = 1.0
    field.decision_source = "RULE"
    field.recommended_value = rule.recommended_value
    field.label_rule_id = rule.id
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            actor_user_id=rule.created_by_user_id,
            event_type="field_mapped",
            provider="label_rule",
            confidence=1.0,
            details={
                "field_id": str(field.id),
                "mapped_key": rule.mapped_key,
                "label_rule_id": str(rule.id),
            },
        )
    )
    db.flush()
    recompute_stored_profile_status(db, profile)
    return 1


def reset_rule_profile(db: Session, rule: FormLabelRule, profile: FormProfile) -> int:
    fields = list(
        db.scalars(
            select(FormProfileField).where(
                FormProfileField.form_profile_id == profile.id,
                FormProfileField.label_rule_id == rule.id,
                FormProfileField.decision_source == "RULE",
            )
        ).all()
    )
    for field in fields:
        field.mapped_key = "unknown"
        field.confidence = 0.0
        field.recommended_value = ""
        field.label_rule_id = None
    if fields:
        db.flush()
        recompute_stored_profile_status(db, profile)
    return len(fields)


def profile_ids_for_rule(db: Session, rule: FormLabelRule) -> list[UUID]:
    rows = db.execute(
        select(FormProfile.id, FormProfileField)
        .join(Company, Company.id == FormProfile.company_id)
        .join(FormProfileField, FormProfileField.form_profile_id == FormProfile.id)
        .where(
            Company.project_id == rule.project_id,
            FormProfileField.required.is_(True),
            FormProfileField.field_type == rule.field_type,
            ~FormProfileField.decision_source.in_(("MANUAL", "POLICY")),
        )
        .order_by(FormProfile.id, FormProfileField.position)
    ).all()
    return list(
        dict.fromkeys(profile_id for profile_id, field in rows if unresolved_for_rule(field, rule))
    )


def reset_profile_ids(db: Session, rule: FormLabelRule) -> list[UUID]:
    return list(
        db.scalars(
            select(FormProfile.id)
            .join(Company, Company.id == FormProfile.company_id)
            .join(FormProfileField, FormProfileField.form_profile_id == FormProfile.id)
            .where(
                Company.project_id == rule.project_id,
                FormProfileField.label_rule_id == rule.id,
                FormProfileField.decision_source == "RULE",
            )
            .distinct()
            .order_by(FormProfile.id)
        ).all()
    )


def enqueue_readiness(db: Session, project_id: UUID, *, source: str) -> None:
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status.in_(("queued", "running")),
        )
    )
    if active is None:
        add_operation_job(
            db,
            OperationJob(
                project_id=project_id,
                operation_type="form_dm_readiness",
                payload={source: True},
            ),
        )


def run_form_label_rule(
    db: Session, job: OperationJob, worker_id, stop_requested, progress
) -> None:
    rule_id = (job.payload or {}).get("rule_id")
    rule = db.get(FormLabelRule, rule_id) if rule_id else None
    action = str((job.payload or {}).get("action") or "apply")
    profile_ids = []
    if rule is not None and rule.project_id == job.project_id:
        profile_ids = (
            reset_profile_ids(db, rule) if action == "reset" else profile_ids_for_rule(db, rule)
        )
    job.total_count = len(profile_ids)
    job.processed_count = job.success_count = job.failed_count = 0
    db.commit()
    for start in range(0, len(profile_ids), 100):
        job = db.get(OperationJob, job.id)
        if job is None or stop_requested(db, job, worker_id):
            return
        rule = db.get(FormLabelRule, rule_id)
        for profile_id in profile_ids[start : start + 100]:
            profile = db.get(FormProfile, profile_id)
            success = profile is not None and rule is not None
            if success:
                if action == "reset":
                    reset_rule_profile(db, rule, profile)
                elif rule.status == "ACTIVE":
                    apply_rule_to_profile(db, rule, profile)
                else:
                    success = False
            if not progress(db, job, worker_id, success):
                return
    if profile_ids:
        enqueue_readiness(db, job.project_id, source="requested_after_form_label_rule")
        db.commit()


def apply_after_analysis(db: Session, company: Company, profiles: list[FormProfile]) -> int:
    rules = list(
        db.scalars(
            select(FormLabelRule).where(
                FormLabelRule.project_id == company.project_id,
                FormLabelRule.status == "ACTIVE",
            )
        ).all()
    )
    changed = sum(
        apply_rule_to_profile(db, rule, profile) for profile in profiles for rule in rules
    )
    if changed:
        enqueue_readiness(db, company.project_id, source="requested_after_form_label_rule_analysis")
    return changed
