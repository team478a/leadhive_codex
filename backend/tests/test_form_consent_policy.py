from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from app.form_dm_readiness_routes import classify_profile
from app.models import (
    ApprovalRequest,
    FormAnalysisLog,
    FormDelivery,
    FormDmReadinessResult,
    FormProfileField,
    OperationJob,
    OutreachAuditEvent,
    ProjectMember,
)
from app.services.form_consent_policy import (
    apply_after_analysis,
    apply_policy_to_profile,
    reset_policy_profile,
    run_consent_policy,
)
from app.services.form_intelligence.consent import CONSENT_POLICY_VERSION
from app.services.form_intelligence.profile_status import recompute_stored_profile_status
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def add_consent(profile, *, position=10, **changes):
    values = {
        "form_profile_id": profile.id,
        "position": position,
        "name": f"consent-{position}",
        "label": "個人情報の取扱いに同意",
        "field_type": "checkbox",
        "required": True,
        "mapped_key": "privacy_consent",
        "confidence": 1.0,
        "decision_source": "RULE",
        "recommended_value": "",
        "options": [{"value": "yes", "label": "同意する"}],
    }
    values.update(changes)
    return FormProfileField(**values)


def enable(project, user):
    project.consent_policy_enabled = True
    project.consent_policy_version = CONSENT_POLICY_VERSION
    project.consent_policy_enabled_by_user_id = user.id
    project.consent_policy_enabled_at = datetime.now(timezone.utc)


def snapshot(db, project, company, profile):
    job = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="completed",
        total_count=1,
        processed_count=1,
        success_count=1,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()
    db.add(
        FormDmReadinessResult(
            job_id=job.id,
            company_id=company.id,
            profile_id=profile.id,
            primary_reason="NEEDS_CONSENT_REVIEW",
            secondary_reasons=[],
            review_queue_eligible=True,
        )
    )
    db.commit()
    return job


def test_policy_applies_only_safe_fields_and_keeps_manual_decisions(form_source, db, users):
    project, _, _, profile = form_source[:4]
    enable(project, users[0])
    fields = [
        add_consent(profile),
        add_consent(
            profile,
            position=11,
            mapped_key="newsletter_consent",
            label="メールマガジン配信",
            required=False,
        ),
        add_consent(
            profile,
            position=12,
            mapped_key="newsletter_consent",
            label="メールマガジン配信",
            required=True,
        ),
        add_consent(profile, position=13, label="個人情報とキャンペーン配信に同意"),
        add_consent(
            profile,
            position=14,
            decision_source="MANUAL",
            recommended_value="yes",
        ),
    ]
    db.add_all(fields)
    db.commit()

    changed = apply_policy_to_profile(db, project, profile)
    db.commit()

    assert changed == 2
    assert (fields[0].decision_source, fields[0].recommended_value) == ("POLICY", "yes")
    assert (fields[1].decision_source, fields[1].recommended_value) == ("POLICY", "")
    assert fields[2].decision_source == "RULE"
    assert fields[3].decision_source == "RULE"
    assert fields[4].decision_source == "MANUAL"
    assert profile.form_status == "REVIEW_REQUIRED"
    assert (
        db.scalar(
            select(func.count())
            .select_from(FormAnalysisLog)
            .where(FormAnalysisLog.event_type == "policy_applied")
        )
        == 2
    )


def test_policy_resolves_consent_and_changed_text_returns_to_review(form_source, db, users):
    project, company, _, profile = form_source[:4]
    enable(project, users[0])
    profile.form_status = "REVIEW_REQUIRED"
    profile.review_reason = "同意内容を人が確認してください。"
    field = add_consent(profile)
    db.add(field)
    db.commit()

    assert classify_profile(db, company, profile)["primary_reason"] == "NEEDS_CONSENT_REVIEW"
    assert apply_policy_to_profile(db, project, profile) == 1
    assert profile.form_status == "READY"
    assert classify_profile(db, company, profile)["primary_reason"] != "NEEDS_CONSENT_REVIEW"
    field.label = "個人情報とメルマガ配信に同意"
    recompute_stored_profile_status(db, profile)

    assert profile.form_status == "REVIEW_REQUIRED"
    assert "人による確認" in profile.review_reason


def test_disabled_policy_does_nothing_and_reanalysis_hook_preserves_manual(form_source, db, users):
    project, company, _, profile = form_source[:4]
    automatic = add_consent(profile)
    manual = add_consent(
        profile,
        position=11,
        decision_source="MANUAL",
        recommended_value="yes",
    )
    db.add_all([automatic, manual])
    db.commit()

    assert apply_after_analysis(db, company, [profile]) == 0
    enable(project, users[0])
    assert apply_after_analysis(db, company, [profile]) == 1
    db.commit()

    assert automatic.decision_source == "POLICY"
    assert manual.decision_source == "MANUAL"
    assert db.scalar(
        select(OperationJob.id).where(OperationJob.operation_type == "form_dm_readiness")
    )


def test_reset_reverts_only_policy_fields(form_source, db, users):
    project, _, _, profile = form_source[:4]
    enable(project, users[0])
    policy = add_consent(profile, decision_source="POLICY", recommended_value="yes", confidence=1.0)
    manual = add_consent(
        profile,
        position=11,
        decision_source="MANUAL",
        recommended_value="yes",
    )
    db.add_all([policy, manual])
    db.commit()

    assert reset_policy_profile(db, profile) == 1

    assert (policy.decision_source, policy.recommended_value, policy.confidence) == (
        "RULE",
        "",
        0.0,
    )
    assert manual.decision_source == "MANUAL"


def test_owner_enable_api_records_audit_and_enqueues_without_execution(
    auth, form_source, db, users
):
    project = form_source[0]
    before_approvals = db.scalar(select(func.count()).select_from(ApprovalRequest))
    before_deliveries = db.scalar(select(func.count()).select_from(FormDelivery))

    response = auth.post(
        f"/api/projects/{project.id}/consent-policy/enable",
        json={"policy": CONSENT_POLICY_VERSION, "accepted": True},
    )

    assert response.status_code == 202, response.text
    db.refresh(project)
    assert project.consent_policy_enabled is True
    job = db.scalar(select(OperationJob).where(OperationJob.operation_type == "consent_policy"))
    assert job.status == "queued" and job.payload["action"] == "apply"
    audit = db.scalar(
        select(OutreachAuditEvent).where(OutreachAuditEvent.event == "consent policy enabled")
    )
    assert audit.actor_id == users[0].id
    assert CONSENT_POLICY_VERSION in audit.reason

    job.status = "completed"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    reset_response = auth.post(
        f"/api/projects/{project.id}/consent-policy/reset",
        json={"policy": CONSENT_POLICY_VERSION, "accepted": True},
    )
    assert reset_response.status_code == 202, reset_response.text
    assert db.scalar(
        select(OutreachAuditEvent.id).where(
            OutreachAuditEvent.event == "consent policy reset requested"
        )
    )
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == before_approvals
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == before_deliveries


def test_non_owner_cannot_change_policy(auth, form_source, db, users):
    project = form_source[0]
    db.add(ProjectMember(project_id=project.id, user_id=users[1].id, role="editor"))
    db.commit()
    assert auth.post("/api/auth/logout").status_code == 204
    assert (
        auth.post(
            "/api/auth/login",
            json={"email": users[1].email, "password": "test-only-long-password"},
        ).status_code
        == 200
    )

    endpoint = f"/api/projects/{project.id}/consent-policy/enable"
    assert auth.get(f"/api/projects/{project.id}/consent-policy").json()["can_manage"] is False
    assert (
        auth.post(endpoint, json={"policy": CONSENT_POLICY_VERSION, "accepted": True}).status_code
        == 404
    )


def test_policy_job_processes_queue_in_place(form_source, db, users):
    project, company, _, profile = form_source[:4]
    enable(project, users[0])
    profile.form_status = "REVIEW_REQUIRED"
    profile.review_reason = "同意内容を人が確認してください。"
    field = add_consent(profile)
    db.add(field)
    snapshot(db, project, company, profile)
    job = OperationJob(
        project_id=project.id,
        operation_type="consent_policy",
        status="running",
        payload={"action": "apply"},
        worker_id=uuid4(),
    )
    db.add(job)
    db.commit()

    def not_stopped(_db, _job, _worker):
        return False

    def record_progress(session, current, _worker, success):
        current.processed_count += 1
        current.success_count += int(success)
        current.failed_count += int(not success)
        session.commit()
        return True

    run_consent_policy(db, job, job.worker_id, not_stopped, record_progress)

    assert job.total_count == 1
    assert job.processed_count == 1
    assert field.decision_source == "POLICY"
    assert profile.form_status == "READY"
