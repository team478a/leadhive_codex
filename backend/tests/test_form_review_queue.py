import csv
import io
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import object_session

from app.models import (
    FormAnalysisLog,
    FormDmReadinessResult,
    FormProfileField,
    MasterFormReview,
    OperationJob,
    Organization,
)
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def make_reviewable(source):
    project, _, _, profile, _, fields = source
    project_id = project.id
    fields[1].mapped_key = "unknown"
    fields[1].confidence = 0.1
    profile.form_status = "REVIEW_REQUIRED"
    profile.review_reason = "入力項目の確認が必要です。"
    db = object_session(project)
    job = OperationJob(project_id=project_id, operation_type="form_dm_readiness", payload={})
    db.add(job)
    db.commit()
    job.status, job.worker_id = "running", uuid4()
    db.commit()
    from app.worker import run_form_dm_readiness

    run_form_dm_readiness(db, job, job.worker_id)
    db.refresh(job)
    job.status, job.finished_at = "completed", datetime.now(timezone.utc)
    db.commit()
    return f"/api/projects/{project_id}/form-review-queue"


def test_queue_is_read_only_and_returns_review_fingerprint(auth, form_source, db):
    profile = form_source[3]
    profile_id, before = profile.id, profile.updated_at
    path = make_reviewable(form_source)

    response = auth.get(path)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["read_only"] is True
    assert result["external_requests"] == 0
    assert result["total"] == 1
    assert len(result["items"][0]["fingerprint"]) == 64
    db.expire_all()
    assert db.get(type(profile), profile_id).updated_at == before


def test_queue_summary_counts_unresolved_consent_and_is_read_only(auth, form_source, db):
    project, _, _, profile, _, fields = form_source
    profile_id = profile.id
    profile_type = type(profile)
    path = make_reviewable(form_source)
    profile = db.get(profile_type, profile_id)
    additions = [
        FormProfileField(
            form_profile_id=profile.id,
            position=9,
            name="reading1",
            label="よみがな (必須)",
            field_type="text",
            required=True,
            mapped_key="unknown",
            confidence=0.1,
            decision_source="RULE",
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=10,
            name="reading2",
            label="よみがな（必須）",
            field_type="text",
            required=True,
            mapped_key="unknown",
            confidence=0.1,
            decision_source="RULE",
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=11,
            name="reading3",
            label="よみがな※",
            field_type="text",
            required=True,
            mapped_key="unknown",
            confidence=0.1,
            decision_source="RULE",
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=12,
            name="manual",
            label="手動で決定済み",
            field_type="text",
            required=True,
            mapped_key="unknown",
            confidence=0.1,
            decision_source="MANUAL",
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=13,
            name="technical",
            label="仕組み用",
            field_type="hidden",
            required=True,
            mapped_key="unknown",
            confidence=0.1,
            decision_source="DOM",
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=14,
            name="privacy",
            label="個人情報の取扱いに同意",
            field_type="checkbox",
            required=True,
            mapped_key="privacy_consent",
            confidence=1.0,
            decision_source="RULE",
            options=[{"value": "yes", "label": "同意する"}],
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=15,
            name="mixed",
            label="個人情報とメールマガジン配信に同意",
            field_type="checkbox",
            required=False,
            mapped_key="privacy_consent",
            confidence=1.0,
            decision_source="RULE",
            options=[{"value": "yes", "label": "同意する"}],
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=16,
            name="newsletter",
            label="メルマガ登録",
            field_type="checkbox",
            required=False,
            mapped_key="newsletter_consent",
            confidence=1.0,
            decision_source="RULE",
            options=[{"value": "yes", "label": "登録する"}],
        ),
        FormProfileField(
            form_profile_id=profile.id,
            position=17,
            name="formula",
            label="=SUM(A1:A2)",
            field_type="text",
            required=True,
            mapped_key="unknown",
            confidence=0.1,
            decision_source="RULE",
        ),
    ]
    profile.review_reason = "=入力項目の確認が必要です。"
    db.add_all(additions)
    db.commit()
    before_jobs = db.scalar(select(func.count()).select_from(OperationJob))
    before_logs = db.scalar(select(func.count()).select_from(FormAnalysisLog))
    before_updated_at = profile.updated_at

    response = auth.get(path + "/summary")

    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["total"] == 1
    assert summary["by_readiness_reason"]["NEEDS_MAPPING_REVIEW"] == 1
    assert summary["by_review_message"] == [{"message": "=入力項目の確認が必要です。", "count": 1}]
    reading = next(
        item
        for item in summary["unresolved_required_labels"]
        if item["normalized_label"] == "よみがな"
    )
    assert reading == {
        "normalized_label": "よみがな",
        "field_type": "text",
        "form_count": 1,
        "example_labels": ["よみがな (必須)", "よみがな※", "よみがな（必須）"],
    }
    labels = {item["normalized_label"] for item in summary["unresolved_required_labels"]}
    assert "手動で決定済み" not in labels and "仕組み用" not in labels
    assert summary["consent_fields"] == {
        "privacy_only_single_checkbox": 1,
        "mixed_privacy_newsletter": 1,
        "other": 1,
    }
    db.refresh(profile)
    assert db.scalar(select(func.count()).select_from(OperationJob)) == before_jobs
    assert db.scalar(select(func.count()).select_from(FormAnalysisLog)) == before_logs
    assert profile.updated_at == before_updated_at

    exported = auth.get(path + "/summary?format=csv")
    assert exported.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    formula_values = {row["key"] for row in rows if row["section"] != "total"}
    assert "'=入力項目の確認が必要です。" in formula_values
    assert "'=sum(a1:a2)" in formula_values


def test_queue_summary_requires_project_read_access(auth, form_source, db, users):
    outsider_email = users[1].email
    path = make_reviewable(form_source) + "/summary"
    assert auth.post("/api/auth/logout").status_code == 204
    assert (
        auth.post(
            "/api/auth/login",
            json={"email": outsider_email, "password": "test-only-long-password"},
        ).status_code
        == 200
    )

    assert auth.get(path).status_code == 404


def test_review_confirmation_is_profile_bound_and_non_executable(auth, form_source, db):
    profile_id = form_source[3].id
    path = make_reviewable(form_source)
    item = auth.get(path).json()["items"][0]
    decisions = [
        {
            "field_id": field["id"],
            "mapped_key": "message" if field["name"] == "message" else "email",
            "recommended_value": "営業文面" if field["name"] == "message" else "",
            "consent_checked": False,
        }
        for field in item["fields"]
    ]
    payload = {
        "action": "CONFIRM",
        "expected_fingerprint": item["fingerprint"],
        "expected_fields_hash": item["fields_hash"],
        "confirmed_no_sales_prohibition": True,
        "field_decisions": decisions,
    }
    endpoint = f"/api/form-profiles/{item['profile_id']}/review-decision"

    changed = dict(payload, expected_fingerprint="b" * 64)
    assert auth.post(endpoint, json=changed).status_code == 409

    response = auth.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    log = db.scalar(
        select(FormAnalysisLog).where(
            FormAnalysisLog.form_profile_id == profile_id,
            FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
        )
    )
    assert log is not None
    assert log.details["send_authorized"] is False
    assert log.details["execution_allowed"] is False


def test_required_privacy_consent_cannot_be_confirmed_unchecked(auth, form_source, db):
    profile_id = form_source[3].id
    path = make_reviewable(form_source)
    from app.models import FormProfileField

    consent = FormProfileField(
        form_profile_id=profile_id,
        position=10,
        name="privacy",
        label="個人情報の取扱いに同意",
        field_type="checkbox",
        required=True,
        mapped_key="privacy_consent",
        options=[{"value": "yes", "label": "同意する"}],
        confidence=1.0,
        decision_source="MANUAL",
    )
    db.add(consent)
    db.commit()
    item = auth.get(path).json()["items"][0]
    payload = {
        "action": "CONFIRM",
        "expected_fingerprint": item["fingerprint"],
        "expected_fields_hash": item["fields_hash"],
        "confirmed_no_sales_prohibition": True,
        "field_decisions": [
            {
                "field_id": field["id"],
                "mapped_key": "privacy_consent"
                if field["id"] == str(consent.id)
                else "message"
                if field["name"] == "message"
                else "email",
                "recommended_value": "",
                "consent_checked": False,
            }
            for field in item["fields"]
        ],
    }

    response = auth.post(f"/api/form-profiles/{profile_id}/review-decision", json=payload)

    assert response.status_code == 422


def test_do_not_send_is_not_saved_as_reusable_form_review(auth, form_source, db):
    project = form_source[0]
    organization = Organization(name="Review organization")
    db.add(organization)
    db.flush()
    project.organization_id = organization.id
    db.commit()
    path = make_reviewable(form_source)
    item = auth.get(path).json()["items"][0]
    payload = {
        "action": "DO_NOT_SEND",
        "expected_fingerprint": item["fingerprint"],
        "expected_fields_hash": item["fields_hash"],
        "confirmed_no_sales_prohibition": False,
        "do_not_send_reason": "WRONG_PURPOSE",
    }

    response = auth.post(f"/api/form-profiles/{item['profile_id']}/review-decision", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "DO_NOT_SEND"
    assert db.scalar(select(MasterFormReview.id)) is None


def test_confirm_requires_no_sales_prohibition_confirmation(auth, form_source):
    path = make_reviewable(form_source)
    item = auth.get(path).json()["items"][0]
    payload = {
        "action": "CONFIRM",
        "expected_fingerprint": item["fingerprint"],
        "expected_fields_hash": item["fields_hash"],
        "confirmed_no_sales_prohibition": False,
        "field_decisions": [
            {
                "field_id": field["id"],
                "mapped_key": "message" if field["name"] == "message" else "email",
                "recommended_value": "" if field["name"] != "message" else "営業文面",
                "consent_checked": False,
            }
            for field in item["fields"]
        ],
    }

    response = auth.post(f"/api/form-profiles/{item['profile_id']}/review-decision", json=payload)

    assert response.status_code == 422


def test_unreviewed_ready_form_uses_only_sales_prohibition_confirmation(auth, form_source, db):
    project, company, _, profile = form_source[:4]
    profile.form_status = "READY"
    profile.delivery_supported = True
    profile.sales_contact_status = "ALLOWED"
    profile.captcha_type = "CAPTCHA_NONE"
    profile.confirmation_page = False
    snapshot = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="completed",
        payload={},
        total_count=1,
        processed_count=1,
        success_count=1,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.flush()
    db.add(
        FormDmReadinessResult(
            job_id=snapshot.id,
            company_id=company.id,
            profile_id=profile.id,
            primary_reason="READY",
            secondary_reasons=[],
            review_queue_eligible=False,
        )
    )
    db.commit()
    endpoint = f"/api/projects/{project.id}/form-review-queue"

    queue = auth.get(endpoint).json()

    assert queue["total"] == 1
    item = queue["items"][0]
    assert item["ready_confirmation_only"] is True
    assert item["fields"] == []
    assert item["groups"] == []
    assert item["saved_groups"] == []
    decision_url = f"/api/form-profiles/{profile.id}/review-decision"
    payload = {
        "action": "CONFIRM",
        "expected_fingerprint": item["fingerprint"],
        "expected_fields_hash": item["fields_hash"],
        "confirmed_no_sales_prohibition": False,
    }
    assert auth.post(decision_url, json=payload).status_code == 422

    payload["confirmed_no_sales_prohibition"] = True
    response = auth.post(decision_url, json=payload)

    assert response.status_code == 200, response.text
    log = db.scalar(
        select(FormAnalysisLog).where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
        )
    )
    assert log.details["review_mode"] == "READY_CONFIRMATION_ONLY"
    assert log.details["send_authorized"] is False
    assert log.details["execution_allowed"] is False
    assert auth.get(endpoint).json()["total"] == 0
