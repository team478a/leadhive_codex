import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import CollectionFactReview, ProjectMember
from app.services.collection_conditions import evaluate
from app.services.collection_fact_reviews import company_hash, result
from tests import test_collection_conditions as condition_tests
from tests.test_collection_conditions import condition


@pytest.fixture
def sample(db, auth):
    return condition_tests.sample.__wrapped__(db, auth)


def payload(company, kind="AREA", value="姫路市", outcome="MATCH", version=0):
    return dict(
        condition_type=kind,
        value=value,
        outcome=outcome,
        expected_version=version,
        expected_company_hash=company_hash(company),
        source_url="https://example.test/about",
        evidence_excerpt="この店舗の所在地と事業内容を公開ページで確認しました。",
    )


@pytest.mark.parametrize("kind,value", [("AREA", "姫路市"), ("INDUSTRY", "美容院")])
@pytest.mark.parametrize("priority", ["MUST", "WANT", "EXCLUDE"])
def test_human_fact_truth_and_withdrawal(auth, db, sample, kind, value, priority):
    _, _, company = sample
    predicate = condition(priority, value, kind)
    company.address = "兵庫県姫路市本町1"
    company.business_type = "美容院"
    company.source_keyword = "姫路市 美容院"
    db.commit()
    assert evaluate(db, company, [predicate])["conditions"][0]["outcome"] == "UNKNOWN"
    url = f"/api/companies/{company.id}/collection-fact-reviews"
    response = auth.post(url, json=payload(company, kind, value))
    assert response.status_code == 201
    row = db.scalar(
        select(CollectionFactReview).where(CollectionFactReview.company_id == company.id)
    )
    assert row.actor_user_id and row.project_id == company.project_id
    found = evaluate(db, company, [predicate])
    assert found["conditions"][0]["outcome"] == "MATCH"
    assert found["state"] == ("NO_MATCH" if priority == "EXCLUDE" else "MATCH")
    assert auth.post(url, json=payload(company, kind, value, "NO_MATCH", 1)).status_code == 201
    negative = evaluate(db, company, [predicate])
    assert negative["conditions"][0]["outcome"] == "NO_MATCH"
    assert negative["state"] == ("NO_MATCH" if priority == "MUST" else "MATCH")
    assert auth.post(url, json=payload(company, kind, value, "UNKNOWN", 2)).status_code == 201
    assert result(db, company, kind, value)["reason"] == "FACT_REVIEW_WITHDRAWN"
    assert (
        len(
            db.scalars(
                select(CollectionFactReview).where(CollectionFactReview.company_id == company.id)
            ).all()
        )
        == 3
    )
    assert auth.delete(url).status_code == 405 and auth.put(url, json={}).status_code == 405


def test_fact_conflict_expiration_and_context(auth, db, sample):
    _, _, company = sample
    url = f"/api/companies/{company.id}/collection-fact-reviews"
    data = payload(company)
    assert auth.post(url, json=data).status_code == 201
    assert auth.post(url, json=data).status_code == 409
    assert (
        result(db, company, "AREA", "姫路市", datetime.now(timezone.utc) + timedelta(hours=25))[
            "outcome"
        ]
        == "UNKNOWN"
    )
    assert result(db, company, "AREA", "神戸市")["outcome"] == "UNKNOWN"
    assert result(db, company, "INDUSTRY", "姫路市")["outcome"] == "UNKNOWN"
    company.address = "兵庫県神戸市本町1"
    db.commit()
    assert result(db, company, "AREA", "姫路市")["reason"] == "ENTITY_CHANGED"
    assert auth.post(url, json={**data, "expected_version": 1}).status_code == 409
    assert auth.post(url, json=payload(company, version=1)).status_code == 201


@pytest.mark.parametrize(
    "source",
    [
        "",
        "http://127.0.0.1/a",
        "https://user:secret@example.test",
        "https://example.test/?token=secret",
        "javascript:alert(1)",
    ],
)
def test_public_evidence_only(auth, db, sample, source):
    _, _, company = sample
    response = auth.post(
        f"/api/companies/{company.id}/collection-fact-reviews",
        json={**payload(company), "source_url": source},
    )
    assert response.status_code == 422
    assert (
        db.scalar(
            select(CollectionFactReview.id).where(CollectionFactReview.company_id == company.id)
        )
        is None
    )


def test_fact_roles_and_agent(auth, db, sample, users):
    project, _, company = sample
    url = f"/api/companies/{company.id}/collection-fact-reviews"
    data = payload(company)
    assert auth.post(url, json=data, headers={"Authorization": "Bearer agent"}).status_code == 403
    project.user_id = users[1].id
    db.commit()
    assert auth.post(url, json=data).status_code == 404
    member = ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer")
    db.add(member)
    db.commit()
    assert auth.post(url, json=data).status_code == 404
    member.role = "editor"
    db.commit()
    assert auth.post(url, json=data).status_code == 201


def test_fact_schema_rejects_agent_claims_and_unknown_types(auth, db, sample):
    _, _, company = sample
    url = f"/api/companies/{company.id}/collection-fact-reviews"
    for change in [
        {"condition_type": "ACTIVE_JOB"},
        {"outcome": "CORRECT"},
        {"approved": True},
        {"actor_user_id": str(company.id)},
    ]:
        assert auth.post(url, json={**payload(company), **change}).status_code == 422


def test_migration_refuses_review_loss(monkeypatch):
    from types import SimpleNamespace

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/1372277c354d_collection_fact_human_reviews.py"
    )
    spec = importlib.util.spec_from_file_location("fact_review_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=lambda _: 1))
    monkeypatch.setattr(module.context, "get_x_argument", lambda **_: {})
    monkeypatch.setattr(
        module.op, "drop_table", lambda *_: pytest.fail("Must not drop recorded facts")
    )
    with pytest.raises(RuntimeError, match="Export fact reviews"):
        module.downgrade()
