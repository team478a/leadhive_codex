"""Provider-free tests for an explicitly bounded paid-search operation."""

import pytest
from pydantic import ValidationError

from app import worker
from app.config import settings
from app.schema_workflow import OperationJobInput
from app.services import collection_scheduler, target_collection
from tests.test_target_collection import candidate, result, setup_job


@pytest.mark.parametrize("fair", [False, True])
def test_limit_applies_across_keywords(auth, db, monkeypatch, fair):
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", fair)
    monkeypatch.setattr(worker, "apply_application_settings", lambda db: None)
    _, job_id = setup_job(
        auth, db, monkeypatch, keywords=["a", "b", "c"], target=10, request_limit=2
    )
    calls = []

    def search(k, r, n, p):
        calls.append((k, p))
        return [candidate(f"{k}{p}")]

    runner = collection_scheduler if fair else target_collection
    monkeypatch.setattr(runner, "search_serper_page", search)
    worker.run_once()
    state = result(auth, job_id)["collection_progress"]
    assert len(calls) == state["requests"] == state["request_budget"] == 2
    assert state["stop_reason"] == "REQUEST_BUDGET_REACHED"
    retry = auth.post(f"/api/operations/{job_id}/retry")
    assert retry.status_code == 409
    assert len(calls) == 2


@pytest.mark.parametrize("fair", [False, True])
def test_failed_search_consumes_limit_before_network(auth, db, monkeypatch, fair):
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", fair)
    monkeypatch.setattr(worker, "apply_application_settings", lambda db: None)
    _, job_id = setup_job(auth, db, monkeypatch, target=10, request_limit=1)
    calls = []

    def fail(*args):
        calls.append(args)
        raise RuntimeError("simulated interruption after request reservation")

    monkeypatch.setattr(
        collection_scheduler if fair else target_collection, "search_serper_page", fail
    )
    worker.run_once()
    retry = auth.post(f"/api/operations/{job_id}/retry")
    assert retry.status_code == 202
    worker.run_once()
    assert len(calls) == 1
    assert result(auth, retry.json()["id"])["collection_progress"]["requests"] == 1


@pytest.mark.parametrize("value", [0, 51, -1, True, 2.5, "2"])
def test_invalid_limit_rejected(value):
    with pytest.raises(ValidationError):
        OperationJobInput(
            operation_type="collect_search",
            source="serper",
            keywords=["a"],
            region="大阪",
            target_count=10,
            search_request_limit=value,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "google_places"},
        {"source": "gbizinfo"},
        {"target_count": None},
        {"operation_type": "web_analysis", "source": None, "keywords": [], "region": ""},
    ],
)
def test_other_operations_reject_limit(changes):
    payload = dict(
        operation_type="collect_search",
        source="serper",
        keywords=["a"],
        region="大阪",
        target_count=10,
        search_request_limit=2,
    )
    with pytest.raises(ValidationError):
        OperationJobInput(**{**payload, **changes})
