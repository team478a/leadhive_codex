import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from app import worker
from app.models import Company, OperationJob


def make_project(auth):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    return auth.post(
        "/api/projects",
        json={
            "project_name": "バックグラウンド処理",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "全国",
            "status": "active",
        },
    ).json()


def add_company(auth, db, project_id):
    auth.post(
        f"/api/projects/{project_id}/collection-jobs/urls",
        json={"urls": ["https://operation.example"]},
    )
    data = auth.get(f"/api/projects/{project_id}/companies").json()[0]
    return db.get(Company, data["id"])


def test_enqueue_worker_progress_and_duplicate_prevention(auth, db, monkeypatch):
    project = make_project(auth)
    company = add_company(auth, db, project["id"])
    response = auth.post(
        f"/api/projects/{project['id']}/operations",
        json={"operation_type": "web_analysis", "company_ids": [str(company.id)]},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert (
        auth.post(
            f"/api/projects/{project['id']}/operations",
            json={"operation_type": "web_analysis"},
        ).status_code
        == 409
    )

    def completed(_db, item, force=False):
        item.analysis_status = "completed"
        _db.commit()
        return item

    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "analyze", completed)
    assert worker.run_once()
    job = auth.get(f"/api/projects/{project['id']}/operations").json()[0]
    assert job["status"] == "completed"
    assert job["total_count"] == 1
    assert job["processed_count"] == 1 and job["success_count"] == 1
    assert job["attempt_count"] == 1


def test_stale_job_recovery_and_attempt_limit(auth, db, monkeypatch):
    project = make_project(auth)
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    retryable = OperationJob(
        project_id=project["id"],
        operation_type="web_analysis",
        status="running",
        attempt_count=1,
        worker_id=uuid.uuid4(),
        lease_expires_at=expired,
        total_count=4,
        processed_count=2,
        success_count=2,
    )
    exhausted = OperationJob(
        project_id=project["id"],
        operation_type="ai_analysis",
        status="running",
        attempt_count=3,
        worker_id=uuid.uuid4(),
        lease_expires_at=expired,
    )
    db.add_all([retryable, exhausted])
    db.commit()
    monkeypatch.setattr(worker.settings, "worker_max_attempts", 3)

    assert worker.recover_stale_jobs(db) == (1, 1)
    db.refresh(retryable)
    db.refresh(exhausted)
    assert retryable.status == "queued"
    assert retryable.processed_count == 0
    assert retryable.worker_id is None and retryable.lease_expires_at is None
    assert exhausted.status == "failed"
    assert exhausted.finished_at is not None


def test_worker_stops_after_losing_lease(auth, db):
    project = make_project(auth)
    original_worker = uuid.uuid4()
    job = OperationJob(
        project_id=project["id"],
        operation_type="web_analysis",
        status="running",
        attempt_count=1,
        worker_id=uuid.uuid4(),
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db.add(job)
    db.commit()
    assert worker.stop_requested(db, job, original_worker)


def test_cancel_retry_validation_and_access_isolation(auth, users):
    project = make_project(auth)
    created = auth.post(
        f"/api/projects/{project['id']}/operations",
        json={
            "operation_type": "collect_search",
            "source": "serper",
            "keywords": ["運送会社"],
            "region": "大阪",
            "max_results": 10,
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    cancelled = auth.post(f"/api/operations/{job_id}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["finished_at"] is not None
    retried = auth.post(f"/api/operations/{job_id}/retry")
    assert retried.status_code == 202 and retried.json()["status"] == "queued"
    assert auth.post(f"/api/operations/{job_id}/retry").status_code == 409
    assert (
        auth.post(
            f"/api/projects/{project['id']}/operations",
            json={"operation_type": "collect_search", "keywords": []},
        ).status_code
        == 422
    )

    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/projects/{project['id']}/operations").status_code == 404
    assert auth.post(f"/api/operations/{job_id}/cancel").status_code == 404
