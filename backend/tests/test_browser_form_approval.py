from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.config import Settings
from app.models import (
    ApprovalRequest,
    FormAnalysisLog,
    FormDmReadinessResult,
    FormProfileField,
    OperationJob,
)
from app.services.form_review_binding import fields_hash
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def test_browser_delivery_is_disabled_by_default():
    assert Settings(_env_file=None).browser_form_delivery_enabled is False


def make_browser_profile(db, source):
    project, company, draft, profile, _, fields = source
    profile.analysis_source = "browser"
    profile.form_status = "REVIEW_REQUIRED"
    profile.delivery_supported = False
    profile.compatibility_reason_code = "CONTACT_FORM_7"
    profile.confirmation_page = True
    for field, selector in zip(fields, ("#email", "#message"), strict=True):
        field.selector = selector
    db.add(
        FormAnalysisLog(
            company_id=company.id,
            form_profile_id=profile.id,
            event_type="manual_corrected",
            provider="manual",
            details={
                "operation": "form_review_confirmed",
                "profile_fingerprint": profile.fingerprint,
                "fields_hash": fields_hash(profile, fields),
                "confirmed_no_sales_prohibition": True,
            },
        )
    )
    db.commit()
    return project, company, draft, profile, fields


def test_browser_ready_is_classified_from_stored_same_site_analysis(db, form_source):
    from app.form_dm_readiness_routes import classify_profile

    _, company, _, profile, _ = make_browser_profile(db, form_source)

    result = classify_profile(db, company, profile)

    assert result == {"primary_reason": "BROWSER_READY", "secondary_reasons": []}


def test_browser_plan_is_bound_into_human_approval_without_external_fetch(
    auth, db, form_source, monkeypatch
):
    project, company, draft, profile, fields = make_browser_profile(db, form_source)

    def forbidden(*args, **kwargs):
        pytest.fail("Browser-plan preparation must not access or submit the site")

    monkeypatch.setattr("app.services.form_delivery.inspect_form", forbidden)
    monkeypatch.setattr("app.services.form_delivery.submit_form", forbidden)
    preview_response = auth.get(f"/api/outreach-drafts/{draft.id}/browser-form-approval-preview")

    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["proposal"]["delivery_method"] == "browser_form"
    plan = preview["proposal"]["browser_form_plan"]
    assert plan["form_url"] == "https://approval.example/contact"
    assert plan["action_url"] == "https://approval.example/contact/submit"
    assert plan["submission_kind"] == "contact_form_7"
    assert plan["captcha_type"] == "CAPTCHA_NONE"

    created = auth.post(
        f"/api/outreach-drafts/{draft.id}/browser-form-approval-request",
        json={"expected_preparation_hash": preview["preparation_hash"]},
    )

    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["delivery_method"] == "browser_form"
    assert proposal["payload_snapshot"]["browser_form_plan"] == {
        **plan,
        "fields": sorted(plan["fields"], key=lambda field: field["profile_field_id"]),
    }
    assert (
        proposal["payload_snapshot"]["browser_form_plan_hash"] == preview["browser_form_plan_hash"]
    )
    assert proposal["status"] == "PENDING"
    assert db.scalar(
        select(ApprovalRequest.id).where(
            ApprovalRequest.id == UUID(proposal["id"]),
            ApprovalRequest.company_id == company.id,
            ApprovalRequest.project_id == project.id,
        )
    )
    assert all(field.selector for field in fields)

    generic = auth.post(f"/api/projects/{project.id}/approval-requests", json=preview["proposal"])
    assert generic.status_code == 409

    stored = db.get(ApprovalRequest, UUID(proposal["id"]))
    altered_snapshot = dict(stored.payload_snapshot)
    altered_plan = dict(altered_snapshot["browser_form_plan"])
    altered_plan["fields"] = [dict(field) for field in altered_plan["fields"]]
    altered_plan["fields"][0]["value"] = "改ざん"
    altered_snapshot["browser_form_plan"] = altered_plan
    stored.payload_snapshot = altered_snapshot
    from app.services.human_approval import valid_browser_form_plan

    assert not valid_browser_form_plan(stored)


def test_uncertain_field_ai_suggestion_is_saved_and_requested_only_once(
    auth, db, form_source, monkeypatch
):
    from app.services.form_intelligence.providers import DecisionBatch, FieldDecision

    _, company, draft, profile, fields = make_browser_profile(db, form_source)
    db.add(
        FormProfileField(
            form_profile_id=profile.id,
            position=2,
            selector="#department",
            name="department",
            label="部署",
            field_type="text",
            required=False,
            mapped_key="unknown",
            confidence=0.0,
        )
    )
    db.commit()
    refreshed_fields = list(
        db.scalars(
            select(FormProfileField)
            .where(FormProfileField.form_profile_id == profile.id)
            .order_by(FormProfileField.position, FormProfileField.id)
        )
    )
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            event_type="manual_corrected",
            provider="manual",
            details={
                "operation": "form_review_confirmed",
                "profile_fingerprint": profile.fingerprint,
                "fields_hash": fields_hash(profile, refreshed_fields),
                "confirmed_no_sales_prohibition": True,
            },
        )
    )
    db.commit()

    class Provider:
        name = "test-provider"

        def __init__(self):
            self.calls = 0

        def decide(self, context):
            self.calls += 1
            assert [field.name for field in context.fields] == ["department"]
            return DecisionBatch(
                decisions=[FieldDecision(2, "department", 0.95)], provider=self.name
            )

    provider = Provider()
    monkeypatch.setattr(
        "app.services.browser_form_preparation.get_form_decision_provider", lambda: provider
    )

    first = auth.get(f"/api/outreach-drafts/{draft.id}/browser-form-approval-preview")
    second = auth.get(f"/api/outreach-drafts/{draft.id}/browser-form-approval-preview")

    assert first.status_code == second.status_code == 200
    assert provider.calls == 1
    logs = db.scalars(
        select(FormAnalysisLog).where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == "browser_delivery_plan_ai",
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].details["attempted"] is True
    department_id = db.scalar(
        select(FormProfileField.id).where(
            FormProfileField.form_profile_id == profile.id,
            FormProfileField.name == "department",
        )
    )
    assert logs[0].details["decisions"][str(department_id)]["mapped_key"] == "department"
    assert (
        first.json()["proposal"]["browser_form_plan"]
        == second.json()["proposal"]["browser_form_plan"]
    )
    assert len(fields) == 2

    from app.services.browser_form_preparation import preparation as browser_preparation

    db.delete(logs[0])
    db.commit()
    unsuggested, _ = browser_preparation(db, company, draft, allow_ai_suggestion=False)
    assert provider.calls == 1
    department = next(
        field for field in unsuggested.browser_form_plan.fields if field.name == "department"
    )
    assert department.mapped_key == "unknown"


def test_browser_ready_queue_and_bulk_proposal_require_saved_review(auth, db, form_source):
    project, company, draft, profile, fields = make_browser_profile(db, form_source)
    db.delete(
        db.scalar(
            select(FormAnalysisLog).where(
                FormAnalysisLog.form_profile_id == profile.id,
                FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
            )
        )
    )
    readiness_job = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="completed",
        payload={},
        total_count=1,
        processed_count=1,
        success_count=1,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(readiness_job)
    db.flush()
    db.add(
        FormDmReadinessResult(
            job_id=readiness_job.id,
            company_id=company.id,
            profile_id=profile.id,
            primary_reason="BROWSER_READY",
            secondary_reasons=[],
            review_queue_eligible=True,
        )
    )
    db.commit()

    queue_path = f"/api/projects/{project.id}/form-review-queue"
    response = auth.get(queue_path)
    assert response.status_code == 200, response.text
    queue_item = response.json()["items"][0]
    assert queue_item["ready_confirmation_only"] is False

    review = auth.post(
        f"/api/form-profiles/{profile.id}/review-decision",
        json={
            "action": "CONFIRM",
            "expected_fingerprint": queue_item["fingerprint"],
            "expected_fields_hash": queue_item["fields_hash"],
            "confirmed_no_sales_prohibition": True,
            "field_decisions": [
                {
                    "field_id": field["id"],
                    "mapped_key": "message" if field["name"] == "message" else "email",
                    "recommended_value": "営業文面" if field["name"] == "message" else "",
                    "consent_checked": False,
                }
                for field in queue_item["fields"]
            ],
        },
    )
    assert review.status_code == 200, review.text

    batch = auth.post(
        f"/api/projects/{project.id}/form-approval-requests/bulk", json={"all_ready": True}
    )
    assert batch.status_code == 202, batch.text
    job = db.get(OperationJob, UUID(batch.json()["id"]))
    worker_id = uuid4()
    job.status, job.worker_id = "running", worker_id
    db.commit()

    from app.worker import run_form_approval_batch

    run_form_approval_batch(db, job, worker_id)
    db.refresh(job)
    assert job.payload["results"][0]["status"] == "created", job.payload["results"]
    proposal = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.company_id == company.id,
            ApprovalRequest.source_draft_id == draft.id,
        )
    )
    assert proposal is not None
    assert proposal.delivery_method == "browser_form"
    assert proposal.status == "PENDING"
    assert all(field.selector for field in fields)
