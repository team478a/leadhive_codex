from contextlib import nullcontext

import pytest
from sqlalchemy import func, select

from app import worker
from app.models import CollectionJob, Company
from app.services import target_collection
from app.services.collection import Candidate, ExternalServiceError
from app.services.collection_jobs import save_candidates, start_job
from tests.test_collection import make_project


def test_serper_pagination_keeps_batch_size(monkeypatch):
    from app.config import settings
    from app.services import collection
    from tests.test_collection import FakeClient

    calls = []
    monkeypatch.setattr(settings, "serper_api_key", "test-only")
    monkeypatch.setattr(
        collection.httpx,
        "Client",
        lambda **kwargs: FakeClient(
            [{"organic": [{"title": "Company", "link": "https://company.example.test"}]}], calls
        ),
    )
    assert len(collection.search_serper_page("SNS", "大阪", 10, 2)) == 1
    assert calls[0][1]["json"]["page"] == 2
    assert calls[0][1]["json"]["num"] == 10


def setup_job(auth, db, monkeypatch, *, keywords=None, target=3, request_limit=None):
    project = make_project(auth)
    response = auth.post(
        f"/api/projects/{project['id']}/operations",
        json=dict(
            operation_type="collect_search",
            source="serper",
            keywords=keywords or ["a"],
            region="大阪",
            target_count=target,
            **({"search_request_limit": request_limit} if request_limit is not None else {}),
        ),
    )
    assert response.status_code == 202
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    return project, response.json()["id"]


def candidate(name):
    return Candidate(name, f"https://{name}.example.test")


def result(auth, job_id):
    project_id = auth.get("/api/projects").json()[0]["id"]
    response = auth.get(f"/api/projects/{project_id}/operations")
    assert response.status_code == 200
    return next(row for row in response.json() if row["id"] == job_id)


def test_target_stops_on_saved_count_not_raw_hits(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch)
    calls = []

    def search(keyword, region, limit, page):
        calls.append(page)
        return (
            [candidate("one"), candidate("one")]
            if page == 1
            else [candidate("two"), candidate("three"), candidate("four")]
        )

    monkeypatch.setattr(target_collection, "search_serper_page", search)
    assert worker.run_once()
    job = result(auth, job_id)
    assert job["status"] == "completed"
    assert job["collection_progress"]["collected_count"] == 3
    assert job["collection_progress"]["stop_reason"] == "TARGET_REACHED"
    assert calls == [1, 2]
    assert db.scalar(select(func.count()).select_from(Company)) == 3


def test_no_growth_ends_query_and_moves_to_next(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch, keywords=["a", "b"], target=4)
    calls = []

    def search(keyword, region, limit, page):
        calls.append((keyword, page))
        return [candidate(keyword)]

    monkeypatch.setattr(target_collection, "search_serper_page", search)
    worker.run_once()
    job = result(auth, job_id)
    assert calls == [("a", 1), ("a", 2), ("b", 1), ("b", 2)]
    assert job["collection_progress"]["collected_count"] == 2
    assert job["collection_progress"]["stop_reason"] == "QUERIES_EXHAUSTED"


def test_existing_project_records_do_not_count_toward_new_goal(auth, db, monkeypatch):
    project, job_id = setup_job(auth, db, monkeypatch, target=2)
    old = start_job(db, project["id"], "url", "", "")
    save_candidates(db, old, [candidate("old")])
    monkeypatch.setattr(target_collection, "search_serper_page", lambda *args: [candidate("old")])
    worker.run_once()
    assert result(auth, job_id)["collection_progress"]["collected_count"] == 0


def test_request_budget_is_distinct_from_no_growth(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch, target=10)
    monkeypatch.setattr(target_collection, "REQUEST_BUDGET", 2)
    monkeypatch.setattr(
        target_collection, "search_serper_page", lambda k, r, n, p: [candidate(f"page{p}")]
    )
    worker.run_once()
    state = result(auth, job_id)["collection_progress"]
    assert state["requests"] == 2
    assert state["stop_reason"] == "REQUEST_BUDGET_REACHED"


def test_empty_page_and_aggregator_page_do_not_add_targets(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch, keywords=["a", "b"])
    monkeypatch.setattr(
        target_collection,
        "search_serper_page",
        lambda k, *args: (
            [] if k == "a" else [Candidate("Portal", "https://beauty.hotpepper.jp/test")]
        ),
    )
    worker.run_once()
    state = result(auth, job_id)["collection_progress"]
    assert state["collected_count"] == 0
    assert state["requests"] == 2


def test_source_error_is_not_no_growth(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch)

    def failed(*args):
        raise ExternalServiceError("検索失敗")

    monkeypatch.setattr(target_collection, "search_serper_page", failed)
    worker.run_once()
    job = result(auth, job_id)
    assert job["status"] == "failed"
    assert job["collection_progress"]["stop_reason"] == "SOURCE_ERROR"
    assert db.scalar(select(CollectionJob.status)) == "failed"


def test_retry_keeps_previous_new_targets_and_request_budget(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch, target=2)
    calls = []

    def initial(k, r, n, page):
        calls.append(page)
        if page == 2:
            raise ExternalServiceError("検索失敗")
        return [candidate("one")]

    monkeypatch.setattr(target_collection, "search_serper_page", initial)
    worker.run_once()
    assert result(auth, job_id)["collection_progress"]["collected_count"] == 1
    retry = auth.post(f"/api/operations/{job_id}/retry")
    assert retry.status_code == 202
    monkeypatch.setattr(target_collection, "search_serper_page", lambda *args: [candidate("two")])
    worker.run_once()
    state = result(auth, retry.json()["id"])["collection_progress"]
    assert state["collected_count"] == 2
    assert state["requests"] == 3
    assert state["stop_reason"] == "TARGET_REACHED"


def test_unknown_conditions_are_not_counted_as_matching(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch)
    from app.services import condition_collection

    monkeypatch.setattr(condition_collection, "execution_conditions", lambda *args: ["unknown"])
    monkeypatch.setattr(
        condition_collection,
        "merged_plan",
        lambda *args: type("Plan", (), {"model_dump": lambda self: {}})(),
    )
    monkeypatch.setattr(target_collection, "evaluate", lambda *args: {"state": "REVIEW_REQUIRED"})
    monkeypatch.setattr(target_collection, "search_serper_page", lambda *args: [candidate("one")])
    worker.run_once()
    assert result(auth, job_id)["collection_progress"]["collected_count"] == 0


@pytest.mark.parametrize("condition_state", ["REVIEW_REQUIRED", "NO_MATCH"])
def test_unverified_growth_continues_until_duplicate_page(auth, db, monkeypatch, condition_state):
    _, job_id = setup_job(auth, db, monkeypatch)
    from app.services import condition_collection

    monkeypatch.setattr(condition_collection, "execution_conditions", lambda *args: ["condition"])
    monkeypatch.setattr(
        condition_collection,
        "merged_plan",
        lambda *args: type("Plan", (), {"model_dump": lambda self: {}})(),
    )
    monkeypatch.setattr(target_collection, "evaluate", lambda *args: {"state": condition_state})
    calls = []

    def search(k, r, n, page):
        calls.append(page)
        return [candidate("first" if page == 1 else "second")]

    monkeypatch.setattr(target_collection, "search_serper_page", search)
    worker.run_once()
    state = result(auth, job_id)["collection_progress"]
    assert calls == [1, 2, 3]
    assert state["collected_count"] == 0
    assert state["discovered_count"] == 2
    assert state["review_required_count"] == (2 if condition_state == "REVIEW_REQUIRED" else 0)
    assert state["no_match_count"] == (2 if condition_state == "NO_MATCH" else 0)
    assert state["conditions_applied"] is True
    assert state["stop_reason"] == "QUERIES_EXHAUSTED"


def test_unknown_growth_remains_request_bounded(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch)
    from app.services import condition_collection

    monkeypatch.setattr(condition_collection, "execution_conditions", lambda *args: ["condition"])
    monkeypatch.setattr(
        condition_collection,
        "merged_plan",
        lambda *args: type("Plan", (), {"model_dump": lambda self: {}})(),
    )
    monkeypatch.setattr(target_collection, "evaluate", lambda *args: {"state": "REVIEW_REQUIRED"})
    monkeypatch.setattr(target_collection, "REQUEST_BUDGET", 2)
    monkeypatch.setattr(
        target_collection, "search_serper_page", lambda k, r, n, p: [candidate(f"p{p}")]
    )
    worker.run_once()
    state = result(auth, job_id)["collection_progress"]
    assert state["requests"] == 2
    assert state["collected_count"] == 0
    assert state["discovered_count"] == state["review_required_count"] == 2
    assert state["stop_reason"] == "REQUEST_BUDGET_REACHED"


def test_cancelled_job_does_not_search(auth, db, monkeypatch):
    _, job_id = setup_job(auth, db, monkeypatch)
    assert auth.post(f"/api/operations/{job_id}/cancel").status_code == 200
    calls = []
    monkeypatch.setattr(target_collection, "search_serper_page", lambda *args: calls.append(args))
    worker.run_once()
    assert calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"target_count": 0},
        {"target_count": 501},
        {"source": "google_places"},
        {"source": "gbizinfo"},
        {"operation_type": "web_analysis", "source": None, "keywords": [], "region": ""},
    ],
)
def test_invalid_target_mode_is_rejected(auth, changes):
    project = make_project(auth)
    body = dict(
        operation_type="collect_search",
        source="serper",
        keywords=["a"],
        region="大阪",
        target_count=5,
    )
    body.update(changes)
    assert auth.post(f"/api/projects/{project['id']}/operations", json=body).status_code == 422
