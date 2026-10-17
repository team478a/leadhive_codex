from datetime import datetime, timedelta, timezone

from app.models import WorkerHeartbeat
from app.runtime_version import short_commit
from app.worker import record_worker_heartbeat, stamp_operation_runtime


def test_short_commit_uses_seven_hex_characters():
    assert short_commit("ABCDEF012345") == "abcdef0"
    assert short_commit("unknown") == "unknown"
    assert short_commit(None) == "unknown"


def test_worker_heartbeat_upserts_latest_version_and_host(db):
    record_worker_heartbeat(
        db, instance_id="test-worker", host_name="host-one", commit_id="abc1234"
    )
    record_worker_heartbeat(
        db, instance_id="test-worker", host_name="host-two", commit_id="def5678"
    )

    rows = db.query(WorkerHeartbeat).filter_by(instance_id="test-worker").all()
    assert len(rows) == 1
    assert rows[0].commit_id == "def5678"
    assert rows[0].host_name == "host-two"
    assert rows[0].last_seen_at.tzinfo is not None


def test_operation_job_payload_records_executing_worker(monkeypatch):
    from app import worker
    from app.models import OperationJob

    monkeypatch.setattr(worker, "RUNTIME_COMMIT", "abc1234")
    monkeypatch.setattr(worker, "WORKER_HOST", "worker-host")
    job = OperationJob(payload={"input": "kept"})

    stamp_operation_runtime(job)

    assert job.payload == {
        "input": "kept",
        "executed_by_commit": "abc1234",
        "executed_by_host": "worker-host",
    }


def test_runtime_info_shows_recent_worker_and_omits_stale(auth, db):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            WorkerHeartbeat(
                instance_id="recent-worker",
                host_name="recent-host",
                commit_id="abc1234",
                last_seen_at=now,
            ),
            WorkerHeartbeat(
                instance_id="browser-recent-worker",
                host_name="browser-host",
                commit_id="def5678",
                last_seen_at=now,
            ),
            WorkerHeartbeat(
                instance_id="stale-worker",
                host_name="stale-host",
                commit_id="def5678",
                last_seen_at=now - timedelta(minutes=6),
            ),
        ]
    )
    db.commit()

    response = auth.get("/api/runtime-info")

    assert response.status_code == 200
    assert response.json()["api_commit"]
    workers = response.json()["workers"]
    assert len(workers) == 2
    workers_by_id = {worker["instance_id"]: worker for worker in workers}
    assert workers_by_id["browser-recent-worker"]["worker_type"] == "browser"
    assert workers_by_id["browser-recent-worker"]["commit_id"] == "def5678"
    assert workers_by_id["browser-recent-worker"]["host_name"] == "browser-host"
    assert workers_by_id["recent-worker"]["worker_type"] == "application"
    assert workers_by_id["recent-worker"]["commit_id"] == "abc1234"
    assert workers_by_id["recent-worker"]["host_name"] == "recent-host"
    assert "stale-worker" not in workers_by_id
