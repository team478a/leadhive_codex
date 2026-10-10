"""Real worker/DB replay, with only the external search transport replaced."""

import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app import worker
from app.config import settings
from app.models import CollectionDiscoveryHit, CollectionJob, Company, OperationJob
from app.services import collection, collection_discovery, collection_runtime
from tests.test_collection import FakeResponse
from tests.test_target_collection import setup_job


def replay(auth, db, monkeypatch, pages, *, fair, expected_saved=6):
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(settings, "collection_fair_scheduler_enabled", fair)
    monkeypatch.setattr(settings, "serper_api_key", "test-only-never-transmitted")
    monkeypatch.setattr(FakeResponse, "status_code", 200, raising=False)
    monkeypatch.setattr(worker, "apply_application_settings", lambda db: None)
    project, operation_id = setup_job(auth, db, monkeypatch, target=10)
    calls = []

    class ReplayClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            assert url == "https://google.serper.dev/search"
            operation = db.get(OperationJob, UUID(operation_id))
            # Provenance has been committed by claim_job BEFORE fetching a page.
            assert operation.payload["collection_runtime"]["claim_id"] == str(operation.worker_id)
            page = kwargs["json"].get("page", 1)
            calls.append(page)
            return FakeResponse({"organic": pages[page - 1] if page <= len(pages) else []})

        def get(self, *args, **kwargs):
            raise AssertionError("Crawling is forbidden in Raw replay")

    monkeypatch.setattr(collection.httpx, "Client", ReplayClient)
    assert worker.run_once()
    operation = db.get(OperationJob, UUID(operation_id))
    assert operation.status == "completed"
    assert operation.payload["collection_progress"]["stop_reason"] == "QUERIES_EXHAUSTED"
    assert operation.payload["collection_progress"]["collected_count"] == expected_saved
    assert calls[:2] == [1, 2]  # Filtering must not stop at the old ten saved records.
    assert len(calls) <= 50
    companies = list(db.scalars(select(Company).where(Company.project_id == UUID(project["id"]))))
    assert len(companies) == expected_saved
    assert db.scalar(select(func.count()).select_from(OperationJob)) == 1
    hits = list(db.scalars(select(CollectionDiscoveryHit)))
    assert len(hits) == 20
    assert sum(h.disposition == "SAVED" for h in hits) == expected_saved
    assert sum(h.disposition == "NON_COMPANY_SOURCE" for h in hits) == 20 - expected_saved
    assert all(
        h.disposition != "SAVED"
        for h in hits
        if h.classification in {"JOB_PR", "ARTICLE", "PORTAL_DIRECTORY"}
    )
    collections = list(db.scalars(select(CollectionJob)))
    claim = operation.payload["collection_runtime"]
    for job in collections:
        assert job.discovery_summary["runtime"] == claim["runtime"]
        assert job.discovery_summary["collection_claim"] == claim
    api = auth.get(f"/api/projects/{project['id']}/operations").json()[0]
    assert api["collection_runtime"] == claim
    assert api["collection_runtime_history"] == [claim]
    return operation


def synthetic_pages():
    def official(i):
        return {"title": f"Agency {i} service", "link": f"https://agency-{i}.example.test/service"}

    def article(i):
        return {"title": "会社比較13選", "link": f"https://publisher-{i}.example.test/blogs/list"}

    def job(host):
        return {"title": "求人", "link": f"https://{host}/search/sns"}

    return [
        [official(1), official(2), job("townwork.net"), job("baitoru.com")]
        + [article(i) for i in range(4)]
        + [
            {"title": "企業紹介", "link": "https://web-kanji.com/companies/test"},
            {"title": "紹介", "link": "https://probel.jp/providers/test"},
        ],
        [official(i) for i in range(3, 7)]
        + [job(host) for host in ("next.rikunabi.com", "indeed.com", "townwork.net")]
        + [article(i) for i in range(4, 7)],
    ]


@pytest.mark.parametrize("fair", [False, True])
def test_worker_replay_keeps_raw_but_rejects_non_company_pages(auth, db, monkeypatch, fair):
    replay(auth, db, monkeypatch, synthetic_pages(), fair=fair)


@pytest.mark.parametrize("fair", [False, True])
def test_private_saved_raw_worker_replay(auth, db, monkeypatch, fair):
    path = os.environ.get("LEADHIVE_PRIVATE_RAW_REPLAY")
    if not path:
        pytest.skip("Private saved inputs are not distributed to CI")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pages = data["pages"]
    assert [len(page) for page in pages] == [10, 10]
    replay(auth, db, monkeypatch, pages, fair=fair, expected_saved=5)


def test_fingerprint_tracks_loaded_rules_and_code_without_secrets(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "A" * 40)
    monkeypatch.setenv("SERPER_API_KEY", "secret-must-not-be-recorded")
    monkeypatch.setenv("DATABASE_URL", "credential-must-not-be-recorded")
    initial = collection_runtime.runtime_snapshot()
    assert initial == collection_runtime.runtime_snapshot()
    assert initial["commit"] == "a" * 40
    assert "secret-must-not-be-recorded" not in json.dumps(initial)
    assert "credential-must-not-be-recorded" not in json.dumps(initial)
    monkeypatch.setattr(collection_discovery, "JOB_SOURCE_DOMAINS", {"new.example.test"})
    changed = collection_runtime.runtime_snapshot()
    assert (
        changed["fingerprints"]["classification.rules"]
        != initial["fingerprints"]["classification.rules"]
    )
    monkeypatch.setattr(collection_discovery, "classify_hit", lambda value: ("OTHER", "test"))
    assert (
        collection_runtime.runtime_snapshot()["fingerprints"]["raw.classify_hit"]
        != initial["fingerprints"]["raw.classify_hit"]
    )
    monkeypatch.setenv("RENDER_GIT_COMMIT", "secret-is-not-a-commit")
    assert collection_runtime.runtime_snapshot()["commit"] is None


def test_claim_retry_preserves_previous_runtime(auth, db, monkeypatch):
    _, operation_id = setup_job(auth, db, monkeypatch)
    first = worker.claim_job(db)
    original = first.payload["collection_runtime"]
    first.status = "queued"
    first.worker_id = None
    db.commit()
    second = worker.claim_job(db)
    assert str(second.id) == operation_id
    current = second.payload["collection_runtime"]
    assert current["attempt"] == 2
    assert current["claim_id"] != original["claim_id"]
    assert second.payload["collection_runtime_history"] == [original, current]


def test_old_job_has_unknown_runtime_and_project_boundary(auth, client, users, db, monkeypatch):
    project, operation_id = setup_job(auth, db, monkeypatch)
    response = auth.get(f"/api/projects/{project['id']}/operations").json()[0]
    assert response["collection_runtime"] is None
    assert response["collection_runtime_history"] == []
    from tests.conftest import PASSWORD

    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login", json={"email": users[1].email, "password": PASSWORD}
        ).status_code
        == 200
    )
    assert client.get(f"/api/projects/{project['id']}/operations").status_code == 404
    assert db.get(OperationJob, UUID(operation_id)).payload.get("collection_runtime") is None
