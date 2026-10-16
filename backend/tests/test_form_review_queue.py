from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.models import FormAnalysisLog, OperationJob
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def make_reviewable(source):
    project, _, _, profile, _, fields = source
    fields[1].mapped_key = "unknown"
    fields[1].confidence = 0.1
    profile.form_status = "REVIEW_REQUIRED"
    profile.review_reason = "入力項目の確認が必要です。"
    db = object_session(project)
    job = OperationJob(project_id=project.id, operation_type="form_dm_readiness", payload={})
    db.add(job)
    db.commit()
    job.status, job.worker_id = "running", uuid4()
    db.commit()
    from app.worker import run_form_dm_readiness

    run_form_dm_readiness(db, job, job.worker_id)
    db.refresh(job)
    job.status, job.finished_at = "completed", datetime.now(timezone.utc)
    db.commit()
    return f"/api/projects/{project.id}/form-review-queue"


def test_queue_is_read_only_and_returns_review_fingerprint(auth, form_source, db):
    path = make_reviewable(form_source)
    before = form_source[3].updated_at

    response = auth.get(path)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["read_only"] is True
    assert result["external_requests"] == 0
    assert result["total"] == 1
    assert len(result["items"][0]["fingerprint"]) == 64
    db.expire_all()
    assert db.get(type(form_source[3]), form_source[3].id).updated_at == before


def test_review_confirmation_is_profile_bound_and_non_executable(auth, form_source, db):
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
            FormAnalysisLog.form_profile_id == form_source[3].id,
            FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
        )
    )
    assert log is not None
    assert log.details["send_authorized"] is False
    assert log.details["execution_allowed"] is False


def test_required_privacy_consent_cannot_be_confirmed_unchecked(auth, form_source, db):
    path = make_reviewable(form_source)
    profile = form_source[3]
    from app.models import FormProfileField

    consent = FormProfileField(
        form_profile_id=profile.id,
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

    response = auth.post(f"/api/form-profiles/{profile.id}/review-decision", json=payload)

    assert response.status_code == 422
