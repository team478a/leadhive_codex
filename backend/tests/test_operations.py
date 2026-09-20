import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from threading import Barrier

from sqlalchemy import select

from app import worker
from app.models import AnalysisRefreshSchedule, Company, OperationJob, SearchSchedule
from app.services.collection import Candidate, ExternalServiceError


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
    assert auth.post(f"/api/operations/{job['id']}/acknowledge").status_code == 409


def test_search_collection_worker_records_partial_failure(auth, db, monkeypatch):
    project = make_project(auth)
    created = auth.post(
        f"/api/projects/{project['id']}/operations",
        json={
            "operation_type": "collect_search",
            "source": "serper",
            "keywords": ["成功", "失敗"],
            "region": "大阪",
            "max_results": 10,
        },
    )
    assert created.status_code == 202

    def search(keyword, _region, _max_results):
        if keyword == "失敗":
            raise ExternalServiceError("検索サービスに接続できません。")
        return [Candidate("検索成功企業", "https://async-search.example")]

    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "search_serper", search)
    assert worker.run_once()

    job = auth.get(f"/api/projects/{project['id']}/operations").json()[0]
    assert job["status"] == "failed"
    assert job["total_count"] == 2 and job["processed_count"] == 2
    assert job["success_count"] == 1 and job["failed_count"] == 1
    assert len(auth.get(f"/api/projects/{project['id']}/collection-jobs").json()) == 2
    assert len(auth.get(f"/api/projects/{project['id']}/companies").json()) == 1
    assert auth.get("/api/dashboard").json()["unread_operation_failures"] == 1


def test_search_collection_runs_keywords_concurrently(auth, db, monkeypatch):
    project = make_project(auth)
    created = auth.post(
        f"/api/projects/{project['id']}/operations",
        json={
            "operation_type": "collect_search",
            "source": "serper",
            "keywords": ["alpha", "beta"],
            "region": "東京",
            "max_results": 5,
        },
    )
    assert created.status_code == 202
    barrier = Barrier(2)

    def search(keyword, _region, _max_results):
        barrier.wait(timeout=2)
        return [Candidate(f"{keyword}社", f"https://{keyword}.example")]

    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "search_serper", search)
    assert worker.run_once()
    job = auth.get(f"/api/projects/{project['id']}/operations").json()[0]
    assert job["status"] == "completed" and job["success_count"] == 2


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
    dashboard = auth.get("/api/dashboard").json()
    assert dashboard["operation_statuses"]["failed"] == 1
    assert dashboard["unread_operation_failures"] == 1
    assert dashboard["recent_operations"][0]["acknowledged_at"] is None
    acknowledged = auth.post(f"/api/operations/{exhausted.id}/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_at"] is not None
    assert auth.get("/api/dashboard").json()["unread_operation_failures"] == 0


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


def test_search_schedule_crud_due_enqueue_and_company_limit(auth, db, monkeypatch):
    project = make_project(auth)
    body = {
        "name": "大阪の週次検索",
        "source": "serper",
        "keywords": ["運送会社", "物流会社"],
        "region": "大阪府",
        "max_results": 20,
        "interval_hours": 168,
        "company_limit": 100,
        "active": True,
    }
    created = auth.post(f"/api/projects/{project['id']}/search-schedules", json=body)
    assert created.status_code == 201
    schedule_id = created.json()["id"]
    assert len(auth.get(f"/api/projects/{project['id']}/search-schedules").json()) == 1

    immediate = auth.post(f"/api/search-schedules/{schedule_id}/run")
    assert immediate.status_code == 202
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(
        worker,
        "search_serper",
        lambda *_args: [
            Candidate("企業A", "https://schedule-a.example"),
            Candidate("企業B", "https://schedule-b.example"),
        ],
    )
    assert worker.run_once()
    analytics = auth.get(f"/api/projects/{project['id']}/search-analytics").json()[0]
    assert analytics["run_count"] == 2
    assert analytics["found_count"] == 4 and analytics["saved_count"] == 2
    assert analytics["save_rate"] == 50.0 and analytics["duplicate_rate"] == 50.0

    schedule = db.get(SearchSchedule, schedule_id)
    schedule.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert worker.enqueue_due_schedules(db) == 1
    assert db.get(SearchSchedule, schedule_id).last_enqueued_at is not None
    queued = next(
        item
        for item in auth.get(f"/api/projects/{project['id']}/operations").json()
        if item["status"] == "queued"
    )
    auth.post(f"/api/operations/{queued['id']}/cancel")

    schedule = db.get(SearchSchedule, schedule_id)
    schedule.company_limit = 2
    schedule.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert worker.enqueue_due_schedules(db) == 0
    db.refresh(schedule)
    assert "企業保存上限" in schedule.last_error

    updated = auth.put(f"/api/search-schedules/{schedule_id}", json={**body, "active": False})
    assert updated.status_code == 200 and not updated.json()["active"]
    assert auth.delete(f"/api/search-schedules/{schedule_id}").status_code == 204


def test_analysis_refresh_schedule_crud_and_due_enqueue(auth, db):
    project = make_project(auth)
    company = add_company(auth, db, project["id"])
    company.analysis_status = "completed"
    company.scraped_at = datetime.now(timezone.utc) - timedelta(days=120)
    db.commit()
    body = {"interval_hours": 24, "stale_days": 90, "batch_limit": 25, "active": True}

    created = auth.put(f"/api/projects/{project['id']}/analysis-refresh-schedule", json=body)
    assert created.status_code == 200
    schedule_id = created.json()["id"]
    assert (
        auth.get(f"/api/projects/{project['id']}/analysis-refresh-schedule").json()["stale_days"]
        == 90
    )

    immediate = auth.post(f"/api/projects/{project['id']}/analysis-refresh-schedule/run")
    assert immediate.status_code == 202
    assert immediate.json()["status"] == "queued"
    assert auth.post(f"/api/operations/{immediate.json()['id']}/cancel").status_code == 200

    schedule = db.get(AnalysisRefreshSchedule, schedule_id)
    schedule.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert worker.enqueue_due_refresh_schedules(db) == 1
    db.refresh(schedule)
    assert schedule.last_enqueued_at is not None
    queued = db.scalar(
        select(OperationJob).where(
            OperationJob.project_id == company.project_id,
            OperationJob.status == "queued",
        )
    )
    assert queued.payload == {"company_ids": [str(company.id)], "force": True}
    auth.post(f"/api/operations/{queued.id}/cancel")

    company.scraped_at = datetime.now(timezone.utc)
    schedule.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert worker.enqueue_due_refresh_schedules(db) == 0
    assert (
        auth.put(
            f"/api/projects/{project['id']}/analysis-refresh-schedule",
            json={**body, "active": False},
        ).json()["active"]
        is False
    )
    assert (
        auth.delete(f"/api/projects/{project['id']}/analysis-refresh-schedule").status_code == 204
    )


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
