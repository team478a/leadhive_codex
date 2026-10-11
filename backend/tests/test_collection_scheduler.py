"""Offline provider fixtures exercising the actual persisted runner and worker."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import worker
from app.config import settings
from app.models import CollectionQueryTask, CollectionSearchAttempt, Company, OperationJob
from app.services import collection_scheduler as scheduler
from app.services import target_collection
from app.services.collection import ExternalServiceError
from tests.test_target_collection import candidate, result, setup_job


def setup(auth, db, monkeypatch, **kwargs):
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", True)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _: expire_wait(db))
    return setup_job(auth, db, monkeypatch, **kwargs)


def expire_wait(db):
    for task in db.scalars(select(CollectionQueryTask)):
        task.not_before = None
    db.commit()


def attempts(db):
    return list(
        db.scalars(select(CollectionSearchAttempt).order_by(CollectionSearchAttempt.attempt_order))
    )


def test_fair_pages_keep_duplicate_gap_and_bound_tail(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, keywords=["a", "b"], target=20)
    calls = []

    def search(k, r, n, p):
        calls.append((k, p, n))
        return [candidate(k + ("new" if p >= 3 else "old"))]

    monkeypatch.setattr(scheduler, "search_serper_page", search)
    worker.run_once()
    assert calls == [(k, p, 10) for p in range(1, 6) for k in ("a", "b")]
    state = result(auth, job_id)["collection_progress"]
    assert state["discovered_count"] == 4
    assert state["requests"] == 10
    assert state["stop_reason"] == "QUERIES_EXHAUSTED"
    assert all(t.stop_reason == "NO_NEW_TARGETS" for t in db.scalars(select(CollectionQueryTask)))
    assert all(a.state == "SUCCEEDED" for a in attempts(db))


def test_empty_first_page_does_not_end_query(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, target=1)
    monkeypatch.setattr(
        scheduler, "search_serper_page", lambda k, r, n, p: [] if p == 1 else [candidate("yes")]
    )
    worker.run_once()
    state = result(auth, job_id)["collection_progress"]
    assert state["requests"] == 2 and state["stop_reason"] == "TARGET_REACHED"


def test_nationwide_finishes_prefecture_before_next_and_keeps_global_budget(auth, db, monkeypatch):
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", False)
    project, _ = setup_job(auth, db, monkeypatch)
    monkeypatch.setattr(target_collection, "search_serper_page", lambda *args: [])
    worker.run_once()
    response = auth.post(
        f"/api/projects/{project['id']}/operations",
        json=dict(
            operation_type="collect_search",
            source="serper",
            keywords=["a", "b"],
            region="全国",
            region_mode="prefecture_order",
            target_count=100,
            search_request_limit=6,
        ),
    )
    assert response.status_code == 202
    calls = []
    monkeypatch.setattr(
        scheduler, "search_serper_page", lambda k, r, n, p: calls.append((k, r, p)) or []
    )
    worker.run_once()
    assert calls == [(k, "北海道", p) for p in (1, 2) for k in ("a", "b")] + [
        ("a", "青森県", 1),
        ("b", "青森県", 1),
    ]
    state = result(auth, response.json()["id"])["collection_progress"]
    assert state["requests"] == 6 and state["request_budget"] == 6
    assert state["planned_queries"] == 94 and state["unsearched_queries"] == 90
    assert state["stop_reason"] == "REQUEST_BUDGET_REACHED"


def test_all_empty_queries_are_bounded_and_not_complete_coverage(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, keywords=["a", "b"], target=3)
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: [])
    worker.run_once()
    state = result(auth, job_id)["collection_progress"]
    assert state["requests"] == 4
    assert state["coverage_status"] == "SEARCHES_STOPPED"


def test_global_budget_fairness_and_page_cap(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, keywords=[f"q{i}" for i in range(20)], target=500)
    calls = []

    def search(k, r, n, p):
        calls.append((k, p))
        return [candidate(f"{k}p{p}")]

    monkeypatch.setattr(scheduler, "search_serper_page", search)
    worker.run_once()
    assert [p for _, p in calls[:20]] == [1] * 20
    state = result(auth, job_id)["collection_progress"]
    assert len(calls) == state["requests"] == 50
    assert state["pending_queries"] == 20
    assert state["stop_reason"] == "REQUEST_BUDGET_REACHED"
    assert state["coverage_status"] == "PARTIAL"


@pytest.mark.parametrize("state", ["REVIEW_REQUIRED", "NO_MATCH"])
def test_unconfirmed_growth_reaches_page_cap(auth, db, monkeypatch, state):
    _, job_id = setup(auth, db, monkeypatch)
    monkeypatch.setattr(target_collection, "evaluate", lambda *a: {"state": state})
    from app.services import condition_collection

    monkeypatch.setattr(condition_collection, "execution_conditions", lambda *a: ["condition"])
    monkeypatch.setattr(
        condition_collection,
        "merged_plan",
        lambda *a: type("Plan", (), {"model_dump": lambda self: {}})(),
    )
    monkeypatch.setattr(scheduler, "search_serper_page", lambda k, r, n, p: [candidate(f"new{p}")])
    worker.run_once()
    progress = result(auth, job_id)["collection_progress"]
    assert progress["requests"] == progress["discovered_count"] == 5
    assert progress["collected_count"] == 0
    assert progress["capped_queries"] == 1 and progress["coverage_status"] == "PARTIAL"


def test_retryable_errors_are_reserved_and_do_not_starve_second_query(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, keywords=["a", "b"], target=1)
    calls = []

    def search(k, r, n, p):
        calls.append(k)
        if k == "a":
            raise ExternalServiceError("safe", retryable=True)
        return [candidate("yes")]

    monkeypatch.setattr(scheduler, "search_serper_page", search)
    worker.run_once()
    assert calls == ["a", "b"]
    assert [a.state for a in attempts(db)] == ["FAILED", "SUCCEEDED"]
    assert result(auth, job_id)["collection_progress"]["requests"] == 2


@pytest.mark.parametrize("retryable,delay,expected", [(True, 0, 3), (False, 0, 1), (True, 120, 1)])
def test_error_limits_never_become_stagnation(auth, db, monkeypatch, retryable, delay, expected):
    _, job_id = setup(auth, db, monkeypatch)

    def search(*a):
        raise ExternalServiceError("safe", retryable=retryable, retry_after=delay)

    monkeypatch.setattr(scheduler, "search_serper_page", search)
    worker.run_once()
    state = result(auth, job_id)
    assert state["status"] == "failed"
    assert state["collection_progress"]["requests"] == expected
    assert state["collection_progress"]["stop_reason"] == "SOURCE_ERROR"
    task = db.scalar(select(CollectionQueryTask))
    assert task.stagnant_pages == 0
    from app.models import CollectionJob

    assert db.get(CollectionJob, attempts(db)[0].collection_job_id).error_message == "safe"
    retry = auth.post(f"/api/operations/{job_id}/retry")
    assert retry.status_code == 202
    worker.run_once()
    assert result(auth, retry.json()["id"])["collection_progress"]["requests"] == expected


def test_crash_after_reservation_consumes_budget_and_recovers_once(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, target=1)

    def crash(*a):
        raise RuntimeError("simulated crash after reservation")

    monkeypatch.setattr(scheduler, "search_serper_page", crash)
    worker.run_once()
    assert attempts(db)[0].state == "RESERVED"
    retry = auth.post(f"/api/operations/{job_id}/retry")
    assert retry.status_code == 202
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: [candidate("yes")])
    worker.run_once()
    assert [a.state for a in attempts(db)] == ["UNKNOWN", "SUCCEEDED"]
    state = result(auth, retry.json()["id"])["collection_progress"]
    assert state["requests"] == 2 and state["unknown_attempts"] == 1
    assert db.scalar(select(func.count()).select_from(Company)) == 1
    assert db.scalar(select(func.count()).select_from(CollectionQueryTask)) == 1


def test_atomic_ingestion_cursor_rollback(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, target=1)
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: [candidate("yes")])
    real = scheduler.successful_page

    def crash(*a):
        real(*a)
        raise RuntimeError("fail before commit")

    monkeypatch.setattr(scheduler, "successful_page", crash)
    worker.run_once()
    assert db.scalar(select(func.count()).select_from(Company)) == 0
    assert db.scalar(select(CollectionQueryTask.next_page)) == 1
    assert attempts(db)[0].state == "RESERVED"
    retry = auth.post(f"/api/operations/{job_id}/retry")
    monkeypatch.setattr(scheduler, "successful_page", real)
    worker.run_once()
    assert result(auth, retry.json()["id"])["collection_progress"]["collected_count"] == 1


def test_lost_worker_cannot_ingest_response(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, target=1)

    def search(*a):
        job = db.get(OperationJob, UUID(job_id))
        job.worker_id = uuid4()
        db.commit()
        return [candidate("no")]

    monkeypatch.setattr(scheduler, "search_serper_page", search)
    worker.run_once()
    assert db.scalar(select(func.count()).select_from(Company)) == 0
    assert attempts(db)[0].state == "RESERVED"


def test_plan_identity_and_project_constraints(auth, db, monkeypatch):
    project, job_id = setup(auth, db, monkeypatch)
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: [])
    worker.run_once()
    task = db.scalar(select(CollectionQueryTask))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE collection_query_tasks SET keyword='changed' WHERE id=:id"),
            {"id": task.id},
        )
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE collection_search_attempts SET page=5 WHERE id=:id"),
            {"id": attempts(db)[0].id},
        )
    job = db.get(OperationJob, UUID(job_id))
    job.status, job.worker_id = "running", uuid4()
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    job.payload = {**job.payload, "region": "changed"}
    db.commit()
    with pytest.raises(ValueError, match="plan changed"):
        scheduler.root_and_tasks(db, job, job.worker_id)


def test_flag_only_stamps_new_jobs_and_no_sends(auth, db, monkeypatch):
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", False)
    _, job_id = setup_job(auth, db, monkeypatch)
    job = db.get(OperationJob, UUID(job_id))
    assert "query_plan" not in job.payload
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", True)
    monkeypatch.setattr(target_collection, "search_serper_page", lambda *a: [])
    monkeypatch.setattr(
        scheduler, "search_serper_page", lambda *a: pytest.fail("legacy must not upgrade")
    )
    worker.run_once()
    assert "scheduler_version" not in result(auth, job_id)["collection_progress"]


def test_committed_page_is_not_reingested_after_worker_crash(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, target=1)
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: [candidate("yes")])
    real = scheduler.save_candidates

    def after_commit(*a, **kw):
        real(*a, **kw)
        raise RuntimeError("crash after successful ingestion commit")

    monkeypatch.setattr(scheduler, "save_candidates", after_commit)
    worker.run_once()
    assert attempts(db)[0].state == "SUCCEEDED"
    retry = auth.post(f"/api/operations/{job_id}/retry")
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: pytest.fail("no repeated HTTP"))
    worker.run_once()
    assert result(auth, retry.json()["id"])["collection_progress"]["requests"] == 1
    assert db.scalar(select(func.count()).select_from(Company)) == 1


def test_cancel_after_http_and_resume_preserve_reservation(auth, db, monkeypatch):
    _, job_id = setup(auth, db, monkeypatch, target=1)

    def cancel(*a):
        job = db.get(OperationJob, UUID(job_id))
        job.cancel_requested = True
        db.commit()
        return [candidate("yes")]

    monkeypatch.setattr(scheduler, "search_serper_page", cancel)
    worker.run_once()
    assert result(auth, job_id)["status"] == "cancelled"
    assert db.scalar(select(func.count()).select_from(Company)) == 0
    retry = auth.post(f"/api/operations/{job_id}/retry")
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: [candidate("yes")])
    worker.run_once()
    assert result(auth, retry.json()["id"])["collection_progress"]["requests"] == 2


def test_scheduler_operations_reject_agent_and_isolate_project_viewer(auth, users, db, monkeypatch):
    project, job_id = setup(auth, db, monkeypatch)
    path = f"/api/projects/{project['id']}/operations"
    assert auth.get(path, headers={"Authorization": "Bearer agent-only"}).status_code == 403
    auth.post("/api/auth/logout")
    assert auth.get(path, headers={"Authorization": "Bearer agent-only"}).status_code == 403
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 404
    auth.post("/api/auth/logout")
    auth.post(
        "/api/auth/login", json={"email": users[0].email, "password": "test-only-long-password"}
    )
    auth.post(
        f"/api/projects/{project['id']}/members", json={"email": users[1].email, "role": "viewer"}
    )
    auth.post("/api/auth/logout")
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 200
    assert auth.post(f"/api/operations/{job_id}/cancel").status_code == 404
    assert (
        auth.post(
            path,
            json=dict(
                operation_type="collect_search",
                source="serper",
                keywords=["a"],
                region="大阪",
                target_count=1,
            ),
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "status,retryable",
    [(429, True), (500, True), (503, True), (401, False), (403, False), (404, False)],
)
def test_serper_error_classification_does_not_expose_secrets(monkeypatch, status, retryable):
    import httpx

    from app.services import collection

    monkeypatch.setattr(settings, "serper_api_key", "test-secret-only")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, headers={"Retry-After": "12"}, text="private body")
    )
    real = httpx.Client
    monkeypatch.setattr(collection.httpx, "Client", lambda **kw: real(transport=transport, **kw))
    with pytest.raises(ExternalServiceError) as failure:
        collection.search_serper_page("a", "大阪", 10, 1)
    assert failure.value.retryable is retryable
    assert failure.value.retry_after == 12
    assert (
        "private" not in failure.value.public_message
        and "secret" not in failure.value.public_message
    )


def test_raw_retention_ceiling_is_shared_across_retry_jobs(auth, db, monkeypatch):
    from app.models import CollectionDiscoveryHit, CollectionJob
    from app.services.discovery_capture import capture_serper

    _, job_id = setup(auth, db, monkeypatch, target=1)
    monkeypatch.setattr(settings, "collection_discovery_max_operation_hits", 100)

    def search(*a):
        capture_serper(
            [{"title": "one", "link": f"https://c{i}.example.test"} for i in range(100)],
            page=1,
            requested=10,
        )
        return [candidate("one")]

    def crash(*a, **kw):
        raise RuntimeError("crash before ingestion")

    real = scheduler.save_candidates
    monkeypatch.setattr(scheduler, "search_serper_page", search)
    monkeypatch.setattr(scheduler, "save_candidates", crash)
    worker.run_once()
    assert db.scalar(select(func.count()).select_from(CollectionDiscoveryHit)) == 100
    retry = auth.post(f"/api/operations/{job_id}/retry")
    monkeypatch.setattr(scheduler, "save_candidates", real)
    worker.run_once()
    assert result(auth, retry.json()["id"])["collection_progress"]["requests"] == 2
    assert db.scalar(select(func.count()).select_from(CollectionDiscoveryHit)) == 100
    last = db.get(CollectionJob, attempts(db)[-1].collection_job_id)
    assert last.discovery_summary["captured_count"] == 0
    assert last.discovery_summary["omitted_count"] == 100


def test_query_project_guard_and_terminal_attempt_immutable(auth, db, monkeypatch):
    from tests.test_collection import make_project

    _, job_id = setup(auth, db, monkeypatch)
    monkeypatch.setattr(scheduler, "search_serper_page", lambda *a: [])
    worker.run_once()
    other = make_project(auth)
    first = db.scalar(select(CollectionQueryTask))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            CollectionQueryTask(
                root_operation_id=UUID(job_id),
                project_id=UUID(other["id"]),
                plan_hash=first.plan_hash,
                query_order=1,
                keyword="cross-project",
                region="大阪",
            )
        )
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE collection_search_attempts SET state='RESERVED' WHERE id=:id"),
            {"id": attempts(db)[0].id},
        )
