from datetime import datetime, timedelta, timezone
from uuid import UUID

from app import worker
from app.models import OperationJob, Project, TargetProfile
from app.services import sending_window
from browser_worker.jobs import claim_browser_job, recover_stale_browser_jobs


def _project(db, user):
    profile = TargetProfile(user_id=user.id, profile_name="Browser synthetic fixture")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=user.id,
        target_profile_id=profile.id,
        project_name="Browser synthetic fixture",
        sales_objective="Offline testing only",
        region="全国",
    )
    db.add(project)
    db.flush()
    return project


def test_api_queues_only_synthetic_fixtures_and_deduplicates(auth, db, users, monkeypatch):
    project = _project(db, users[0])
    path = f"/api/projects/{project.id}/browser-form-analysis"
    response = auth.post(
        path,
        json={"fixture": "normal", "fields": {"input[name='name']": "Synthetic"}},
    )
    assert response.status_code == 202
    queued = response.json()
    assert queued["operation_type"] == "browser_form_analysis"
    stored = db.get(OperationJob, UUID(queued["id"]))
    assert stored.payload["fixture"] == "normal"
    assert "url" not in stored.payload

    assert auth.post(path, json={"fixture": "normal", "fields": {}}).status_code == 409
    real_url = auth.post(path, json={"fixture": "normal", "url": "https://example.com"})
    assert real_url.status_code == 422
    assert auth.post(path, json={"fixture": "https://example.com"}).status_code == 422

    monkeypatch.setattr(sending_window, "allowed", lambda _db: True)
    assert worker.claim_job(db) is None
    assert db.get(OperationJob, UUID(queued["id"])).status == "queued"


def test_browser_job_claim_cancel_and_stale_recovery_use_operation_lease(auth, db, users):
    project = _project(db, users[0])
    response = auth.post(
        f"/api/projects/{project.id}/browser-form-analysis",
        json={"fixture": "normal", "fields": {}},
    )
    job_id = response.json()["id"]

    job = claim_browser_job(db)
    assert job is not None and str(job.id) == job_id
    assert job.status == "running"
    assert job.worker_id is not None
    assert job.lease_expires_at is not None
    assert job.payload["executed_by_commit"]
    assert job.payload["executed_by_host"]

    cancelled = auth.post(f"/api/operations/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancel_requested"] is True
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    assert recover_stale_browser_jobs(db) == (0, 0)
    assert db.get(OperationJob, job.id).status == "cancelled"
