from datetime import datetime, timedelta, timezone

from app.models import WorkerHeartbeat
from app.runtime_capacity import cgroup_capacity
from app.runtime_version import short_commit
from app.worker import record_worker_heartbeat, stamp_operation_runtime


def test_short_commit_uses_seven_hex_characters():
    assert short_commit("ABCDEF012345") == "abcdef0"
    assert short_commit("unknown") == "unknown"
    assert short_commit(None) == "unknown"


def test_worker_heartbeat_upserts_latest_version_and_host(db):
    record_worker_heartbeat(
        db,
        instance_id="test-worker",
        host_name="host-one",
        commit_id="abc1234",
        worker_type="application",
    )
    record_worker_heartbeat(
        db,
        instance_id="test-worker",
        host_name="host-two",
        commit_id="def5678",
        worker_type="browser",
    )

    rows = db.query(WorkerHeartbeat).filter_by(instance_id="test-worker").all()
    assert len(rows) == 1
    assert rows[0].commit_id == "def5678"
    assert rows[0].worker_type == "browser"
    assert rows[0].host_name == "host-two"
    assert rows[0].last_seen_at.tzinfo is not None


def test_operation_job_payload_records_executing_worker(monkeypatch):
    from app import worker
    from app.models import OperationJob

    monkeypatch.setattr(worker, "RUNTIME_COMMIT", "abc1234")
    monkeypatch.setattr(worker, "WORKER_HOST", "worker-host")
    monkeypatch.setattr(worker, "WORKER_INSTANCE_ID", "worker-instance")
    job = OperationJob(payload={"input": "kept"})

    stamp_operation_runtime(job)

    assert job.payload == {
        "input": "kept",
        "executed_by_commit": "abc1234",
        "executed_by_host": "worker-host",
        "executed_by_instance_id": "worker-instance",
    }


def test_runtime_info_shows_recent_worker_and_omits_stale(auth, db):
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            WorkerHeartbeat(
                instance_id="browser-prefix-as-application",
                worker_type="application",
                host_name="recent-host",
                commit_id="abc1234",
                last_seen_at=now,
            ),
            WorkerHeartbeat(
                instance_id="worker-without-browser-prefix",
                worker_type="browser",
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
    assert workers_by_id["worker-without-browser-prefix"]["worker_type"] == "browser"
    assert workers_by_id["worker-without-browser-prefix"]["commit_id"] == "def5678"
    assert workers_by_id["worker-without-browser-prefix"]["host_name"] == "browser-host"
    assert workers_by_id["browser-prefix-as-application"]["worker_type"] == "application"
    assert workers_by_id["browser-prefix-as-application"]["commit_id"] == "abc1234"
    assert workers_by_id["browser-prefix-as-application"]["host_name"] == "recent-host"
    assert "stale-worker" not in workers_by_id


def test_runtime_capacity_is_admin_only_and_contains_no_database_url(auth, users, db):
    assert auth.get("/api/admin/runtime-capacity").status_code == 404
    users[0].is_admin = True
    db.commit()
    record_worker_heartbeat(
        db,
        instance_id="capacity-worker",
        host_name="capacity-host",
        commit_id="abc1234",
    )

    response = auth.get("/api/admin/runtime-capacity")

    assert response.status_code == 200
    body = response.json()
    assert body["process"]["cpu_count"] is not None
    assert body["database"]["pool_size"] >= 1
    assert body["workers"][0]["instance_id"] == "capacity-worker"
    serialized = response.text.lower()
    assert "database_url" not in serialized
    assert "postgresql" not in serialized
    assert "password" not in serialized


def test_cgroup_capacity_tolerates_missing_files(tmp_path):
    assert cgroup_capacity(tmp_path) == {
        "cpu_count": __import__("os").cpu_count(),
        "cpu_limit": None,
        "memory_limit_bytes": None,
        "memory_current_bytes": None,
    }
