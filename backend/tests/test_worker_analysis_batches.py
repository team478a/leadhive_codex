from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import worker
from app.models import OperationJob


@pytest.mark.parametrize("operation", ["web_analysis", "ai_analysis"])
def test_analysis_worker_continues_with_remaining_pending_batch(monkeypatch, operation):
    project_id = uuid4()
    worker_id = uuid4()
    job = OperationJob(project_id=project_id, operation_type=operation, payload={"force": False})
    first_batch = [SimpleNamespace(id=index) for index in range(100)]
    second_batch = [SimpleNamespace(id=100), SimpleNamespace(id=101)]
    batches = iter([second_batch, []])
    processed: list[int] = []

    class Database:
        def commit(self):
            pass

        def get(self, model, _identifier):
            return SimpleNamespace(target_profile_id=uuid4())

    monkeypatch.setattr(worker, "selected_companies", lambda *_args: first_batch)
    monkeypatch.setattr(worker, "next_analysis_batch", lambda *_args: next(batches))
    monkeypatch.setattr(worker, "stop_requested", lambda *_args: False)
    monkeypatch.setattr(
        worker,
        "progress",
        lambda _db, _job, _worker, _success: processed.append(1) or True,
    )
    if operation == "web_analysis":
        monkeypatch.setattr(
            worker,
            "analyze",
            lambda *_args: SimpleNamespace(analysis_status="completed"),
        )
        worker.run_web(Database(), job, worker_id)
    else:
        monkeypatch.setattr(
            worker,
            "analyze_company_ai",
            lambda *_args: SimpleNamespace(ai_status="completed"),
        )
        worker.run_ai(Database(), job, worker_id)

    assert len(processed) == 102
    assert job.total_count == 102


@pytest.mark.parametrize("operation", ["web_analysis", "ai_analysis"])
def test_explicit_analysis_selection_does_not_auto_continue(monkeypatch, operation):
    job = OperationJob(
        project_id=uuid4(),
        operation_type=operation,
        payload={"force": False, "company_ids": [str(uuid4())]},
    )
    first_batch = [SimpleNamespace(id=1)]
    monkeypatch.setattr(worker, "selected_companies", lambda *_args: first_batch)
    monkeypatch.setattr(
        worker,
        "next_analysis_batch",
        lambda *_args: pytest.fail("explicitly selected jobs must stay bounded"),
    )
    monkeypatch.setattr(worker, "stop_requested", lambda *_args: False)
    monkeypatch.setattr(worker, "progress", lambda *_args: True)

    class Database:
        def commit(self):
            pass

        def get(self, _model, _identifier):
            return SimpleNamespace(target_profile_id=uuid4())

    if operation == "web_analysis":
        monkeypatch.setattr(
            worker,
            "analyze",
            lambda *_args: SimpleNamespace(analysis_status="completed"),
        )
        worker.run_web(Database(), job, uuid4())
    else:
        monkeypatch.setattr(
            worker,
            "analyze_company_ai",
            lambda *_args: SimpleNamespace(ai_status="completed"),
        )
        worker.run_ai(Database(), job, uuid4())
