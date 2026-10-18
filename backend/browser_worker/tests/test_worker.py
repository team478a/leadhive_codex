import pytest
from sqlalchemy.dialects import postgresql

from app.browser_form_delivery_routes import _dry_run_enabled
from app.config import Settings, settings
from app.services.worker_heartbeat import record_worker_heartbeat
from browser_worker import MAX_CONCURRENT_JOBS, MAX_TASK_SECONDS
from browser_worker import __main__ as browser_worker_main


class FakeSession:
    def __init__(self):
        self.statement = None
        self.commits = 0

    def execute(self, statement):
        self.statement = statement

    def commit(self):
        self.commits += 1


def test_browser_delivery_is_off_by_default_and_execution_is_single_job():
    assert Settings(_env_file=None).browser_form_delivery_enabled is False
    assert Settings(_env_file=None).browser_form_dry_run_enabled is False
    assert settings.browser_form_delivery_enabled is False
    assert MAX_CONCURRENT_JOBS == 1
    assert MAX_TASK_SECONDS == 90


def test_dry_run_gate_is_independent_from_real_delivery(monkeypatch):
    monkeypatch.setattr(settings, "browser_form_delivery_enabled", True)
    monkeypatch.setattr(settings, "browser_form_dry_run_enabled", False)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        _dry_run_enabled()
    assert error.value.status_code == 409

    monkeypatch.setattr(settings, "browser_form_delivery_enabled", False)
    monkeypatch.setattr(settings, "browser_form_dry_run_enabled", True)
    assert _dry_run_enabled() is None


def test_dry_run_execution_gate_is_independent_from_real_delivery(monkeypatch):
    from types import SimpleNamespace

    from app.services import approved_form_worker

    monkeypatch.setattr(settings, "browser_form_delivery_enabled", True)
    monkeypatch.setattr(settings, "browser_form_dry_run_enabled", False)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    calls = []
    monkeypatch.setattr("app.database.SessionLocal", FakeSession)
    monkeypatch.setattr(approved_form_worker, "finish", lambda *args, **kwargs: calls.append(args))

    approved_form_worker.run_browser_dry_run(SimpleNamespace(id="run-id", worker_id="worker-id"))

    assert calls[0][3] == "blocked"


def test_shared_heartbeat_helper_keeps_postgres_upsert_and_commit():
    session = FakeSession()

    record_worker_heartbeat(
        session,
        instance_id="browser-test",
        host_name="test-host",
        commit_id="abc1234",
    )

    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "INSERT INTO worker_heartbeats" in sql
    assert "ON CONFLICT (instance_id) DO UPDATE" in sql
    assert session.statement.table.name == "worker_heartbeats"
    assert session.commits == 1


def test_browser_worker_starts_with_delivery_flag_enabled(monkeypatch):
    class StopAfterOnePoll:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True

    monkeypatch.setattr(settings, "browser_form_delivery_enabled", True)
    monkeypatch.setattr(settings, "worker_paused", False)
    monkeypatch.setattr(browser_worker_main, "Event", StopAfterOnePoll)
    monkeypatch.setattr(browser_worker_main, "heartbeat_once", lambda: None)
    monkeypatch.setattr(browser_worker_main, "run_browser_job_once", lambda: False)

    browser_worker_main.run_forever()
