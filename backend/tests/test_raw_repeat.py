"""Synthetic observations and Human actions, never actual Pilot truth."""

import runpy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app import raw_collection_routes as routes
from app.models import RawLeadReview, RawPairReview, RawReviewSession
from app.services.raw_repeat import candidate_key, pair_features, stability
from tests.test_raw_collection import benchmark, collect


def test_repeat_runs_are_independent_and_bounded(auth, db, monkeypatch):
    b = benchmark(auth)
    rows = collect(auth, b, monkeypatch, count=12)
    path = f"/api/raw-benchmarks/{b['id']}/queries"
    assert (
        auth.post(
            path, json={"source": "serper", "keyword": "美容院", "requested_count": 12}
        ).status_code
        == 409
    )
    assert (
        auth.post(
            path,
            json={"source": "serper", "keyword": "美容院", "requested_count": 10, "repeat": True},
        ).status_code
        == 409
    )
    for i in (2, 3):
        r = auth.post(
            path,
            json={"source": "serper", "keyword": "美容院", "requested_count": 12, "repeat": True},
        )
        assert r.status_code == 201
        report = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
        assert report["queries"][-1]["repeat_index"] == i
    assert (
        auth.post(
            path,
            json={"source": "serper", "keyword": "美容院", "requested_count": 12, "repeat": True},
        ).status_code
        == 409
    )
    migration = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "migrations/versions/29d351ead7ae_raw_repeat_measurements_and_human_pair_.py"
        )
    )
    with pytest.raises(RuntimeError, match="evidence exists"):
        with Operations.context(MigrationContext.configure(db.connection())):
            migration["downgrade"]()
    all_rows = auth.get(f"/api/raw-benchmarks/{b['id']}/snapshots").json()
    assert len(all_rows) == 36 and all_rows[0]["snapshot_hash"] == rows[0]["snapshot_hash"]
    report = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
    assert report["base_requested_count"] == 12 and report["requested_count"] == 36
    q = report["query_groups"][0]
    assert q["raw_stability"]["union"] == 12 and q["raw_stability"]["intersection"] == 12
    assert q["raw_stability"]["repeat_discovery_rate"] == 1
    assert q["human_entity_stability"] is None and report["strict_precision"] is None
    assert report["unique_candidates"] == 12
    assert (
        auth.post(
            path,
            json={"source": "serper", "keyword": "Missing", "requested_count": 1, "repeat": True},
        ).status_code
        == 409
    )
    monkeypatch.setattr(routes, "commit_id", lambda: "changed-commit")
    assert (
        auth.post(
            path,
            json={"source": "serper", "keyword": "美容院", "requested_count": 12, "repeat": True},
        ).status_code
        == 409
    )


def test_sets_missing_features_and_no_automatic_identity():
    result = stability([{"a", "b"}, {"b", "c"}, {"b", "d"}])
    assert result["union"] == 4 and result["intersection"] == 1
    assert result["repeat_discovery_rate"] == 0.25 and result["single_run_rate"] == 0.75
    assert stability([set(), set()])["intersection_rate"] is None
    assert stability([{"a"}])["intersection"] is None
    assert candidate_key({}, "a") != candidate_key({}, "b")
    redacted = {"source": "serper", "redacted_url_fields": ["website"], "source_payload_hash": "a"}
    assert candidate_key(redacted, "a") != candidate_key(
        {**redacted, "source_payload_hash": "b"}, "b"
    )
    left = SimpleNamespace(
        payload={"company_name": "Ａ", "address": "", "website": "https://group.example/a"},
        snapshot_hash="a",
    )
    right = SimpleNamespace(
        payload={"company_name": "A", "address": "", "website": "https://group.example/b"},
        snapshot_hash="b",
    )
    f = pair_features(left, right)
    assert f["name_similarity"] == 1 and f["address_similarity"] is None
    assert f["phone_equal"] is None and f["domain_equal"] is True
    assert f["automatic_identity"] is False


def test_pair_truth_version_hash_session_and_permissions(auth, db, monkeypatch, users):
    b = benchmark(auth)
    rows = collect(auth, b, monkeypatch, count=2)
    pair_path = f"/api/raw-benchmarks/pairs/{rows[0]['id']}/{rows[1]['id']}"
    preview = auth.get(pair_path).json()
    assert preview["features"]["address_similarity"] is None
    left = next(r for r in rows if r["id"] == preview["left_id"])

    def body(outcome, version):
        session = auth.post(
            f"/api/raw-benchmarks/snapshots/{left['id']}/review-start",
            json={"snapshot_hash": left["snapshot_hash"]},
        ).json()["session_id"]
        return {
            "session_id": session,
            "pair_hash": preview["pair_hash"],
            "expected_version": version,
            "outcome": outcome,
            "reason": "Synthetic Human pair truth",
            "evidence_url": "https://evidence.example/page",
        }

    first = body("SAME", 0)
    assert auth.post(pair_path + "/reviews", json=first).status_code == 201
    assert auth.post(pair_path + "/reviews", json=first).status_code == 409
    wrong = body("DIFFERENT", 1)
    assert (
        auth.post(pair_path + "/reviews", json={**wrong, "pair_hash": "0" * 64}).status_code == 409
    )
    assert (
        auth.post(pair_path + "/reviews", json={**wrong, "outcome": "CORRECT"}).status_code == 422
    )
    assert auth.post(pair_path + "/reviews", json=wrong).status_code == 201
    third = body("UNSURE", 2)
    assert auth.post(pair_path + "/reviews", json=third).status_code == 201
    assert db.scalar(select(func.count()).select_from(RawLeadReview)) == 0
    assert db.scalar(select(func.count()).select_from(RawPairReview)) == 3
    report = auth.get(f"/api/raw-benchmarks/{b['id']}/report").json()
    assert report["pair_labels"] == {"SAME": 0, "DIFFERENT": 0, "UNSURE": 1}
    assert report["correct"] == 0 and report["strict_precision"] is None
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(update(RawPairReview).values(outcome="SAME"))
    for statement in (delete(RawPairReview), text("TRUNCATE raw_pair_reviews")):
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(statement)
    expired = body("SAME", 3)
    s = db.get(RawReviewSession, UUID(expired["session_id"]))
    s.started_at -= timedelta(hours=5)
    db.commit()
    assert auth.post(pair_path + "/reviews", json=expired).status_code == 409
    assert (
        auth.get(pair_path, headers={"Authorization": "Bearer synthetic-agent"}).status_code == 403
    )
    other = benchmark(auth)
    other_rows = collect(auth, other, monkeypatch, count=1)
    assert (
        auth.get(f"/api/raw-benchmarks/pairs/{rows[0]['id']}/{other_rows[0]['id']}").status_code
        == 404
    )


def test_viewer_pair_read_only(auth, db, monkeypatch, users):
    from app.models import ProjectMember
    from tests.conftest import PASSWORD

    b = benchmark(auth)
    rows = collect(auth, b, monkeypatch, count=2)
    path = f"/api/raw-benchmarks/pairs/{rows[0]['id']}/{rows[1]['id']}"
    db.add(ProjectMember(project_id=UUID(b["project_id"]), user_id=users[1].id, role="viewer"))
    db.commit()
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    preview = auth.get(path)
    assert preview.status_code == 200
    denied = auth.post(
        path + "/reviews",
        json={
            "session_id": str(users[1].id),
            "pair_hash": preview.json()["pair_hash"],
            "expected_version": 0,
            "outcome": "SAME",
            "reason": "Synthetic review",
            "evidence_url": "https://evidence.example/page",
        },
    )
    assert denied.status_code == 404  # Existing project boundary masks write denial
    assert db.scalar(select(func.count()).select_from(RawPairReview)) == 0
