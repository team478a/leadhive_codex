"""Synthetic tests only; never count fixtures as measured discovery precision."""

import runpy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app import raw_collection_routes as routes
from app.models import (
    ApprovalRequest,
    Company,
    EmailDelivery,
    FormDelivery,
    OperationJob,
    ProjectMember,
    RawBenchmark,
    RawLeadReview,
    RawLeadSnapshot,
    RawQueryRun,
    RawReviewSession,
)
from app.services.collection import ExternalServiceError
from app.services.raw_benchmark import digest
from app.services.raw_capture import capture, capturing
from tests.conftest import PASSWORD


def benchmark(auth):
    response = auth.post(
        "/api/raw-benchmarks", json={"region": "兵庫県姫路市", "industry": "美容院"}
    )
    assert response.status_code == 201
    return response.json()


def collect(auth, b, monkeypatch, keyword="美容院", count=3):
    monkeypatch.setattr(routes.settings, "serper_api_key", "synthetic-only")
    monkeypatch.setattr(routes.settings, "outbound_enabled", False)

    def provider(k, region, maximum):
        assert k == keyword and region == "兵庫県姫路市" and maximum == count
        capture(
            "serper",
            [
                {"title": f"Synthetic {i}", "link": f"https://store{i}.example/"}
                for i in range(count)
            ],
        )
        return []

    monkeypatch.setattr(routes, "search_serper", provider)
    response = auth.post(
        f"/api/raw-benchmarks/{b['id']}/queries",
        json={"source": "serper", "keyword": keyword, "requested_count": count},
    )
    assert response.status_code == 201, response.text
    return auth.get(f"/api/raw-benchmarks/{b['id']}/snapshots").json()


def review(auth, row, outcome, **extra):
    started = auth.post(
        f"/api/raw-benchmarks/snapshots/{row['id']}/review-start",
        json={"snapshot_hash": row["snapshot_hash"]},
    )
    assert started.status_code == 201
    body = {
        "snapshot_hash": row["snapshot_hash"],
        "session_id": started.json()["session_id"],
        "expected_version": row["review"]["version"] if row["review"] else 0,
        "outcome": outcome,
        "reason": "Synthetic Human inspection",
        "evidence_url": "https://evidence.example/page",
        **extra,
    }
    return auth.post(f"/api/raw-benchmarks/snapshots/{row['id']}/reviews", json=body), body


def test_raw_immutable_no_downstream_and_null_precision(auth, db, monkeypatch):
    b = benchmark(auth)
    empty = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
    assert empty["found"] == 0 and empty["strict_precision"] is None and empty["coverage"] is None
    rows = collect(auth, b, monkeypatch)
    assert len(rows) == 3
    for row in rows:
        assert row["payload"]["source_query"] == "美容院 兵庫県姫路市"
        assert row["snapshot_hash"] == digest(row["payload"])
    result = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
    assert result["found"] == 3 and result["reviewed"] == 0
    assert result["field_completeness"]["company_name"]["rate"] is None
    assert result["queries"][0]["marginal_gain"] is None
    assert (
        auth.post(
            f"/api/projects/{b['project_id']}/collection-jobs/search",
            json={
                "source": "serper",
                "keywords": ["美容院"],
                "region": "姫路市",
                "max_results": 20,
            },
        ).status_code
        == 409
    )
    assert (
        auth.post(f"/api/projects/{b['project_id']}/lead-destinations/refresh", json={}).status_code
        == 409
    )
    for model in (Company, OperationJob, ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    for statement in (
        update(RawLeadSnapshot).values(snapshot_hash="a" * 64),
        delete(RawLeadSnapshot),
        text("TRUNCATE raw_lead_snapshots CASCADE"),
        update(RawBenchmark).values(region="Other"),
        update(RawQueryRun).values(keyword="Changed"),
    ):
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(statement)
    migration = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "migrations/versions/111884efd88e_raw_collection_pilot_snapshots_and_.py"
        )
    )
    with pytest.raises(RuntimeError, match="evidence exists"):
        with Operations.context(MigrationContext.configure(db.connection())):
            migration["downgrade"]()


def test_human_truth_metrics_versions_and_duplicate_gain(auth, db, monkeypatch):
    b = benchmark(auth)
    rows = collect(auth, b, monkeypatch)
    assert review(auth, rows[0], "CORRECT", entity_key="store-001")[0].status_code == 201
    assert review(auth, rows[1], "UNCERTAIN")[0].status_code == 201
    assert review(auth, rows[2], "WRONG_AREA")[0].status_code == 201
    rows = collect(auth, b, monkeypatch, keyword="美容室", count=2)
    assert review(auth, rows[3], "DUPLICATE", duplicate_of=rows[0]["id"])[0].status_code == 201
    assert review(auth, rows[4], "CORRECT", entity_key="store-002")[0].status_code == 201
    result = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
    assert result["found"] == 5 and result["reviewed"] == 5 and result["correct"] == 2
    assert result["strict_precision"] == 0.4 and result["resolved_precision"] == 0.5
    assert result["duplicate_rate"] == 0.2 and result["uncertain_rate"] == 0.2
    assert result["unique_correct"] == 2 and result["duplicate_types"]["cross_query"] == 1
    assert [q["marginal_gain"] for q in result["queries"]] == [1, 1]
    assert result["field_completeness"]["website"]["rate"] == 1
    assert result["field_completeness"]["phone"]["rate"] == 0
    row = auth.get(f"/api/raw-benchmarks/{b['id']}/snapshots").json()[0]
    changed, body = review(auth, row, "WRONG_ENTITY")
    assert changed.status_code == 201
    assert (
        auth.post(f"/api/raw-benchmarks/snapshots/{row['id']}/reviews", json=body).status_code
        == 409
    )
    assert db.scalar(select(func.count()).select_from(RawLeadReview)) == 6
    assert auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()["correct"] == 1
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(update(RawLeadReview).values(outcome="CORRECT"))


def test_review_validation_scope_and_time(auth, db, users, monkeypatch):
    b = benchmark(auth)
    row = collect(auth, b, monkeypatch, count=1)[0]
    path = f"/api/raw-benchmarks/snapshots/{row['id']}/review-start"
    assert (
        auth.post(
            path,
            json={"snapshot_hash": row["snapshot_hash"]},
            headers={"Authorization": "Bearer invalid"},
        ).status_code
        == 403
    )
    for outcome, extra in [
        ("INVALID", {}),
        ("CORRECT", {}),
        ("DUPLICATE", {"duplicate_of": row["id"]}),
        ("UNCERTAIN", {"evidence_url": "http://localhost/"}),
    ]:
        assert review(auth, row, outcome, **extra)[0].status_code == 422
    started = auth.post(path, json={"snapshot_hash": row["snapshot_hash"]}).json()
    session = db.get(RawReviewSession, UUID(started["session_id"]))
    session.started_at -= timedelta(hours=5)
    db.commit()
    assert (
        auth.post(
            f"/api/raw-benchmarks/snapshots/{row['id']}/reviews",
            json={
                "snapshot_hash": row["snapshot_hash"],
                "session_id": started["session_id"],
                "expected_version": 0,
                "outcome": "UNCERTAIN",
                "reason": "Synthetic inspection",
                "evidence_url": "https://evidence.example/",
            },
        ).status_code
        == 409
    )
    db.add(ProjectMember(project_id=UUID(b["project_id"]), user_id=users[1].id, role="viewer"))
    db.commit()
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert auth.get(f"/api/raw-benchmarks/{b['id']}/report").status_code == 200
    assert auth.post(path, json={"snapshot_hash": row["snapshot_hash"]}).status_code == 404
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == UUID(b["project_id"])))
    db.commit()
    assert auth.get(f"/api/raw-benchmarks/{b['id']}/report").status_code == 404


def test_source_quota_failure_and_no_automatic_retry(auth, db, monkeypatch):
    b = benchmark(auth)
    rows = collect(auth, b, monkeypatch, count=25)
    assert len(rows) == 25
    path = f"/api/raw-benchmarks/{b['id']}/queries"
    assert (
        auth.post(
            path, json={"source": "google_places", "keyword": "美容院", "requested_count": 1}
        ).status_code
        == 409
    )

    assert (
        auth.post(
            path, json={"source": "serper", "keyword": "美容院", "requested_count": 1}
        ).status_code
        == 409
    )
    assert (
        auth.post(
            path, json={"source": "serper", "keyword": "美容室", "requested_count": 6}
        ).status_code
        == 409
    )

    def fail(*args):
        raise ExternalServiceError("Synthetic provider failure")

    monkeypatch.setattr(routes, "search_serper", fail)
    response = auth.post(path, json={"source": "serper", "keyword": "美容室", "requested_count": 1})
    assert response.status_code == 201 and response.json()["status"] == "FAILED"
    assert (
        auth.post(
            path, json={"source": "serper", "keyword": "美容室", "requested_count": 1}
        ).status_code
        == 409
    )


def test_capture_precedes_adapter_filtering(monkeypatch):
    from app.services import collection
    from tests.test_collection import FakeClient

    calls = []
    monkeypatch.setattr(collection.settings, "serper_api_key", "synthetic-only")
    monkeypatch.setattr(
        collection.httpx,
        "Client",
        lambda **kwargs: FakeClient(
            [
                {
                    "organic": [
                        {"title": "Synthetic portal", "link": "https://example.com/list"},
                        {"title": "Synthetic invalid URL", "link": "invalid"},
                    ]
                }
            ],
            calls,
        ),
    )
    with capturing() as raw:
        candidates = collection.search_serper("Synthetic query", "Synthetic region", 2)
    assert len(raw) == 2 and len(candidates) == 1
    assert raw[1]["website"] == "invalid"
    assert len(calls) == 1


def test_cross_source_duplicates_gain_and_cancel(auth, db, monkeypatch):
    b = benchmark(auth)
    rows = collect(auth, b, monkeypatch, count=1)
    assert review(auth, rows[0], "CORRECT", entity_key="store-001")[0].status_code == 201
    monkeypatch.setattr(routes.settings, "gbizinfo_api_token", "synthetic-only")

    def gbiz(*args):
        capture(
            "gbizinfo",
            [
                {
                    "name": "Synthetic",
                    "location": "Synthetic address",
                    "corporate_number": "1234567890123",
                }
            ],
        )
        return []

    monkeypatch.setattr(routes, "search_gbizinfo", gbiz)
    response = auth.post(
        f"/api/raw-benchmarks/{b['id']}/queries",
        json={"source": "gbizinfo", "keyword": "Synthetic", "requested_count": 1},
    )
    assert response.status_code == 201
    rows = auth.get(f"/api/raw-benchmarks/{b['id']}/snapshots").json()
    assert rows[1]["payload"]["source_stable_id"] == "1234567890123"
    assert review(auth, rows[1], "DUPLICATE", duplicate_of=rows[0]["id"])[0].status_code == 201
    report = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
    assert report["duplicate_types"]["cross_source"] == 1
    assert report["sources"][1]["unique_gain"] == 0
    assert report["queries"][1]["marginal_gain"] == 0
    run = RawQueryRun(
        benchmark_id=UUID(b["id"]),
        ordinal=3,
        source="serper",
        keyword="Interrupted",
        query="Interrupted",
        requested_count=1,
        code_commit="synthetic",
        status="RUNNING",
    )
    db.add(run)
    db.commit()
    assert auth.post(f"/api/raw-benchmarks/{b['id']}/queries/{run.id}/cancel").status_code == 200
    assert auth.post(f"/api/raw-benchmarks/{b['id']}/queries/{run.id}/cancel").status_code == 409
