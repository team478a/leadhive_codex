from contextlib import nullcontext

import pytest
from sqlalchemy import func, select

from app import worker
from app.config import settings
from app.models import Company, ExternalPresenceSearch, OperationJob, Project, ProjectMember
from app.services import collection
from app.services.collection import Candidate
from app.services.collection_jobs import save_candidates, start_job
from tests.test_collection import make_project
from tests.test_collection_conditions import condition, payload


@pytest.fixture
def prepared(auth, db, monkeypatch):
    monkeypatch.setattr(settings, "outbound_enabled", False)
    project = make_project(auth)
    revision = auth.post(
        f"/api/projects/{project['id']}/collection-conditions", json=payload()
    ).json()
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    return project, revision


def body(revision, **changes):
    return dict(
        operation_type="collect_search",
        source="serper",
        keywords=["a"],
        region="test",
        max_results=10,
        condition_request_id=revision["id"],
        condition_version=revision["version"],
        condition_hash=revision["payload_hash"],
        presence_search={"max_extra_searches": 1},
        **changes,
    )


def enqueue(auth, project, revision, changes=None):
    values = body(revision)
    values.update(changes or {})
    return auth.post(f"/api/projects/{project['id']}/operations", json=values)


def primary(keyword, *_):
    return [Candidate(f"Company {keyword}", f"https://{keyword}.example.test", phone="0791234567")]


def test_bound_collection_forces_off_and_limits_results_to_job(auth, db, monkeypatch, prepared):
    project, revision = prepared
    old_job = start_job(db, project["id"], "serper", "old", "test")
    save_candidates(db, old_job, primary("old"))
    response = enqueue(auth, project, revision, {"keywords": ["a", "b"]})
    assert response.status_code == 202
    assert response.json()["condition_version"] == 1
    job_id = response.json()["id"]
    extra = []
    monkeypatch.setattr(worker, "search_serper", primary)

    def search(*args):
        extra.append(args)
        return [
            Candidate("Company a", "https://instagram.com/companya", search_excerpt="0791234567")
        ]

    monkeypatch.setattr(collection, "search_serper", search)
    # A new project revision must not change the already queued job.
    assert (
        auth.post(
            f"/api/projects/{project['id']}/collection-conditions",
            json=payload([condition("WANT")], version=1),
        ).status_code
        == 201
    )
    assert worker.run_once()
    report = auth.get(f"/api/operations/{job_id}/collection-conditions").json()
    assert report["condition_version"] == 1 and report["total_candidates"] == 2
    assert report["page_counts"] == {"MATCH": 1, "NO_MATCH": 0, "REVIEW_REQUIRED": 1}
    assert len(extra) == 1
    assert db.scalar(select(func.count()).select_from(ExternalPresenceSearch)) == 1
    assert not settings.outbound_enabled
    assert (
        auth.get(f"/api/operations/{job_id}/collection-conditions?offset=2").json()[
            "evaluated_count"
        ]
        == 0
    )


@pytest.mark.parametrize("exclude", [False, True])
def test_hard_failure_skips_optional_investigation(auth, db, monkeypatch, prepared, exclude):
    project, _ = prepared
    revision = auth.post(
        f"/api/projects/{project['id']}/collection-conditions",
        json=payload(
            [
                condition("EXCLUDE" if exclude else "MUST"),
                condition("WANT", value="YOUTUBE", key="c2"),
            ],
            version=1,
        ),
    ).json()
    response = enqueue(
        auth,
        project,
        revision,
        {"presence_search": {"modes": {"YOUTUBE": "SEARCH"}, "max_extra_searches": 5}},
    )
    job_id = response.json()["id"]
    monkeypatch.setattr(worker, "search_serper", primary)
    extra = []

    def search(*args):
        extra.append(args)
        return (
            [Candidate("Company a", "https://instagram.com/companya", search_excerpt="0791234567")]
            if exclude
            else []
        )

    monkeypatch.setattr(collection, "search_serper", search)
    assert worker.run_once()
    assert len(extra) == 1 and "instagram.com" in extra[0][0]
    report = auth.get(f"/api/operations/{job_id}/collection-conditions").json()
    assert report["page_counts"]["NO_MATCH"] == 1
    assert db.scalar(select(func.count()).select_from(Company)) == 1  # Preserve the candidate.


def test_zero_budget_stays_review_no_external_verification(auth, monkeypatch, prepared):
    project, revision = prepared
    response = enqueue(auth, project, revision, {"presence_search": {"max_extra_searches": 0}})
    monkeypatch.setattr(worker, "search_serper", primary)
    monkeypatch.setattr(collection, "search_serper", lambda *_: pytest.fail("No extra budget"))
    assert worker.run_once()
    result = auth.get(f"/api/operations/{response.json()['id']}/collection-conditions").json()
    assert result["page_counts"]["REVIEW_REQUIRED"] == 1


def test_cancel_stops_extra_search_preserves_partial_scope(auth, db, monkeypatch, prepared):
    project, revision = prepared
    response = enqueue(auth, project, revision)
    job = db.get(OperationJob, response.json()["id"])

    def cancel(*args):
        job.cancel_requested = True
        db.commit()
        return primary("a")

    monkeypatch.setattr(worker, "search_serper", cancel)
    monkeypatch.setattr(collection, "search_serper", lambda *_: pytest.fail("Cancelled"))
    assert worker.run_once()
    db.refresh(job)
    assert job.status == "cancelled"
    result = auth.get(f"/api/operations/{job.id}/collection-conditions").json()
    assert result["status"] == "cancelled" and result["total_candidates"] == 1


def test_retry_keeps_binding_and_tampered_worker_stops_before_search(
    auth, db, monkeypatch, prepared
):
    project, revision = prepared
    source = enqueue(auth, project, revision).json()
    assert auth.post(f"/api/operations/{source['id']}/cancel").status_code == 200
    retry = auth.post(f"/api/operations/{source['id']}/retry")
    assert retry.status_code == 202 and retry.json()["condition_request_id"] == revision["id"]
    job = db.get(OperationJob, retry.json()["id"])
    job.payload = {
        **job.payload,
        "condition_binding": {**job.payload["condition_binding"], "snapshot": {}},
    }
    db.commit()
    monkeypatch.setattr(worker, "search_serper", lambda *_: pytest.fail("Tampered binding"))
    assert worker.run_once()
    db.refresh(job)
    assert job.status == "failed" and "整合性" in job.error_message
    assert auth.get(f"/api/operations/{job.id}/collection-conditions").status_code == 409
    assert auth.post(f"/api/operations/{job.id}/retry").status_code == 409


def test_binding_validation_and_permissions(auth, db, prepared, users):
    project, revision = prepared
    url = f"/api/projects/{project['id']}/operations"
    assert auth.post(url, json={**body(revision), "condition_hash": "0" * 64}).status_code == 409
    assert auth.post(url, json={**body(revision), "condition_version": 2}).status_code == 409
    missing = body(revision)
    del missing["condition_hash"]
    assert auth.post(url, json=missing).status_code == 422
    assert (
        auth.post(url, json={**body(revision), "operation_type": "web_analysis"}).status_code == 422
    )
    other = make_project(auth)
    assert enqueue(auth, other, revision).status_code == 409
    response = enqueue(auth, project, revision)
    job_id = response.json()["id"]
    assert (
        auth.get(
            f"/api/operations/{job_id}/collection-conditions",
            headers={"Authorization": "Bearer agent"},
        ).status_code
        == 403
    )
    row = db.get(Project, project["id"])
    row.user_id = users[1].id
    db.commit()
    assert auth.get(f"/api/operations/{job_id}/collection-conditions").status_code == 404
    db.add(ProjectMember(project_id=row.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(f"/api/operations/{job_id}/collection-conditions").status_code == 200
    assert auth.post(url, json=body(revision)).status_code == 404


@pytest.mark.parametrize(
    "frozen",
    [{}, {"request_id": "invalid", "version": 1, "payload_hash": "0" * 64, "snapshot": {}}],
)
def test_corrupted_binding_rejects_results_and_retry(auth, db, prepared, frozen):
    project, revision = prepared
    response = enqueue(auth, project, revision).json()
    assert auth.post(f"/api/operations/{response['id']}/cancel").status_code == 200
    job = db.get(OperationJob, response["id"])
    job.payload = {**job.payload, "condition_binding": frozen}
    db.commit()
    assert auth.get(f"/api/operations/{job.id}/collection-conditions").status_code == 409
    assert auth.post(f"/api/operations/{job.id}/retry").status_code == 409
