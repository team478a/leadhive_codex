from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    FormAnalysisLog,
    FormDmReadinessResult,
    FormProfile,
    FormProfileField,
    OperationJob,
    Project,
)
from app.services.form_intelligence.consent import (
    CONSENT_KEYS,
    CONSENT_POLICY_VERSION,
    consent_policy_decision,
)
from app.services.form_intelligence.profile_status import recompute_stored_profile_status
from app.services.operations import add_operation_job


def _field_data(field: FormProfileField) -> dict:
    return {
        "label": field.label,
        "field_type": field.field_type,
        "mapped_key": field.mapped_key,
        "required": field.required,
        "options": field.options if isinstance(field.options, list) else [],
        "decision_source": field.decision_source,
        "recommended_value": field.recommended_value,
    }


def apply_policy_to_profile(
    db: Session,
    project: Project,
    profile: FormProfile,
) -> int:
    if (
        not project.consent_policy_enabled
        or project.consent_policy_version != CONSENT_POLICY_VERSION
    ):
        return 0
    db.flush()
    fields = db.scalars(
        select(FormProfileField).where(FormProfileField.form_profile_id == profile.id)
    ).all()
    changed = 0
    for field in fields:
        if field.mapped_key not in CONSENT_KEYS or field.decision_source == "MANUAL":
            continue
        decision = consent_policy_decision(_field_data(field))
        if decision is None:
            continue
        value = (
            str(field.options[0].get("value") or "")
            if decision == "checked" and field.options
            else ""
        )
        if (
            field.decision_source == "POLICY"
            and field.confidence == 1.0
            and field.recommended_value == value
        ):
            continue
        field.decision_source = "POLICY"
        field.confidence = 1.0
        field.recommended_value = value
        db.add(
            FormAnalysisLog(
                company_id=profile.company_id,
                form_profile_id=profile.id,
                actor_user_id=project.consent_policy_enabled_by_user_id,
                event_type="policy_applied",
                provider="policy",
                confidence=1.0,
                details={
                    "policy": CONSENT_POLICY_VERSION,
                    "field_id": str(field.id),
                    "decision": decision,
                    "project_setting_enabled_by": (
                        str(project.consent_policy_enabled_by_user_id)
                        if project.consent_policy_enabled_by_user_id
                        else None
                    ),
                    "enabled_at": (
                        project.consent_policy_enabled_at.isoformat()
                        if project.consent_policy_enabled_at
                        else None
                    ),
                },
            )
        )
        changed += 1
    if changed:
        db.flush()
        recompute_stored_profile_status(db, profile)
    return changed


def reset_policy_profile(db: Session, profile: FormProfile) -> int:
    fields = db.scalars(
        select(FormProfileField).where(
            FormProfileField.form_profile_id == profile.id,
            FormProfileField.decision_source == "POLICY",
        )
    ).all()
    for field in fields:
        field.decision_source = "RULE"
        field.confidence = 0.0
        field.recommended_value = ""
    if fields:
        db.flush()
        recompute_stored_profile_status(db, profile)
    return len(fields)


def queued_profile_ids(db: Session, project_id: UUID) -> list[UUID]:
    from app.form_dm_readiness_routes import latest_completed_job
    from app.form_review_queue_routes import _queue_filter

    snapshot = latest_completed_job(db, project_id)
    if snapshot is None:
        return []
    return list(
        db.scalars(
            select(FormProfile.id)
            .join(Company, Company.id == FormProfile.company_id)
            .join(FormDmReadinessResult, FormDmReadinessResult.profile_id == FormProfile.id)
            .where(
                Company.project_id == project_id,
                FormDmReadinessResult.job_id == snapshot.id,
                _queue_filter(),
            )
            .distinct()
            .order_by(FormProfile.id)
        ).all()
    )


def reset_profile_ids(db: Session, project_id: UUID) -> list[UUID]:
    return list(
        db.scalars(
            select(FormProfile.id)
            .join(Company, Company.id == FormProfile.company_id)
            .join(FormProfileField, FormProfileField.form_profile_id == FormProfile.id)
            .where(
                Company.project_id == project_id,
                FormProfileField.decision_source == "POLICY",
            )
            .distinct()
            .order_by(FormProfile.id)
        ).all()
    )


def run_consent_policy(db: Session, job: OperationJob, worker_id, stop_requested, progress) -> None:
    action = str((job.payload or {}).get("action") or "apply")
    profile_ids = (
        reset_profile_ids(db, job.project_id)
        if action == "reset"
        else queued_profile_ids(db, job.project_id)
    )
    job.total_count = len(profile_ids)
    job.processed_count = job.success_count = job.failed_count = 0
    db.commit()
    for start in range(0, len(profile_ids), 100):
        job = db.get(OperationJob, job.id)
        if job is None or stop_requested(db, job, worker_id):
            return
        project = db.get(Project, job.project_id)
        for profile_id in profile_ids[start : start + 100]:
            profile = db.get(FormProfile, profile_id)
            success = profile is not None
            if profile is not None:
                if action == "reset":
                    reset_policy_profile(db, profile)
                elif project is not None and project.consent_policy_enabled:
                    apply_policy_to_profile(db, project, profile)
                else:
                    success = False
            if not progress(db, job, worker_id, success):
                return


def enabled_project(db: Session, project_id: UUID) -> Project | None:
    project = db.get(Project, project_id)
    if (
        project is not None
        and project.consent_policy_enabled
        and project.consent_policy_version == CONSENT_POLICY_VERSION
    ):
        return project
    return None


def apply_after_analysis(db: Session, company: Company, profiles: list[FormProfile]) -> int:
    project = enabled_project(db, company.project_id)
    if project is None:
        return 0
    changed = sum(apply_policy_to_profile(db, project, profile) for profile in profiles)
    if changed:
        active = db.scalar(
            select(OperationJob.id).where(
                OperationJob.project_id == company.project_id,
                OperationJob.operation_type == "form_dm_readiness",
                OperationJob.status.in_(("queued", "running")),
            )
        )
        if active is None:
            add_operation_job(
                db,
                OperationJob(
                    project_id=company.project_id,
                    operation_type="form_dm_readiness",
                    payload={"requested_after_consent_policy": True},
                ),
            )
    return changed
