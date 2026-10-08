import pytest
from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    CollectionConditionRequest,
    CollectionFactReview,
    Company,
    EmailDelivery,
    FormDelivery,
    OperationJob,
    ProjectMember,
)
from app.services.condition_summary import summarize
from tests import test_collection_conditions as conditions
from tests.test_collection_conditions import condition, payload


@pytest.fixture
def sample(db, auth):
    return conditions.sample.__wrapped__(db, auth)


def candidate(state, rows):
    return dict(
        state=state,
        conditions=[dict(id=key, priority=p, outcome=o, reason=r) for key, p, o, r in rows],
    )


def test_shortfall_never_counts_unknown_or_optional_conditions():
    snapshot = dict(
        requested_count=3,
        requested_count_explicit=True,
        conditions=[
            dict(id="a", type="AREA", value="地域", priority="MUST"),
            dict(id="w", type="MEDIA_EXISTS", value="INSTAGRAM", priority="WANT"),
        ],
    )
    candidates = [
        candidate("MATCH", [("a", "MUST", "MATCH", "OK"), ("w", "WANT", "UNKNOWN", "NOT_CHECKED")]),
        candidate("REVIEW_REQUIRED", [("a", "MUST", "UNKNOWN", "FACT_REVIEW_REQUIRED")]),
        candidate("NO_MATCH", [("a", "MUST", "NO_MATCH", "DIFFERENT")]),
    ]
    value = summarize(snapshot, candidates, 3)
    assert value["shortfall"] == 2 and value["target_met"] is False
    assert value["counts"] == dict(MATCH=1, NO_MATCH=1, REVIEW_REQUIRED=1)
    assert {r["condition_id"] for r in value["reasons"]} == {"a"}
    partial = summarize(snapshot, candidates, 4)
    assert not partial["complete"] and partial["unevaluated_count"] == 1
    assert partial["shortfall"] is None and partial["target_met"] is None


def test_multiple_stops_are_not_additive_or_potential_unlock():
    snapshot = dict(
        conditions=[
            dict(id=i, type="AREA", value=i, priority=p)
            for i, p in (("a", "EXCLUDE"), ("b", "MUST"))
        ]
    )
    value = summarize(
        snapshot,
        [
            candidate(
                "NO_MATCH",
                [
                    ("a", "EXCLUDE", "MATCH", "PRESENCE_FOUND"),
                    ("b", "MUST", "UNKNOWN", "NOT_CHECKED"),
                ],
            )
        ],
        1,
    )
    assert value["counts"]["NO_MATCH"] == 1
    assert len(value["reasons"]) == 2
    assert all(r["affected_candidates"] == 1 for r in value["reasons"])
    assert value["requested_count"] is None


@pytest.mark.parametrize(
    "explicit,count",
    [(False, 100), (None, 100), (True, None), (True, True), (True, 0), (True, 1001)],
)
def test_unknown_target_and_zero_candidates_are_not_zero_target(explicit, count):
    value = summarize(
        dict(conditions=[], requested_count=count, requested_count_explicit=explicit), [], 0
    )
    assert value["complete"] and value["requested_count"] is None
    assert value["shortfall"] is None and value["target_met"] is None
    assert (
        summarize(dict(conditions=[], requested_count=20, requested_count_explicit=True), [], 0)[
            "shortfall"
        ]
        == 20
    )


def test_summary_scope_integrity_readonly_and_no_hints(auth, db, sample, monkeypatch):
    project, job, company = sample
    from app.services import industry_review_hints

    monkeypatch.setattr(
        industry_review_hints, "hints", lambda *a: pytest.fail("Summary must not extract text")
    )
    row = auth.post(
        f"/api/projects/{project.id}/collection-conditions",
        json=payload(
            [condition(kind="INDUSTRY", value="美容院")],
            requested_count=20,
            requested_count_explicit=True,
            collection_job_id=str(job.id),
        ),
    ).json()
    url = f"/api/collection-conditions/{row['id']}/summary"
    before = {
        m: db.scalar(select(func.count()).select_from(m))
        for m in (
            Company,
            OperationJob,
            CollectionFactReview,
            ApprovalRequest,
            EmailDelivery,
            FormDelivery,
        )
    }
    value = auth.get(url).json()
    assert value["scope"] == "COLLECTION" and value["total_candidates"] == 1
    assert value["counts"]["REVIEW_REQUIRED"] == 1
    assert value["shortfall"] == 20 and value["complete"]
    assert not any(key in value for key in ("company_name", "candidates", "website_text"))
    assert all(
        db.scalar(select(func.count()).select_from(m)) == count for m, count in before.items()
    )
    assert auth.get(url + "?limit=501").status_code == 422
    assert auth.get(url, headers={"Authorization": "Bearer agent"}).status_code == 403
    saved = db.get(CollectionConditionRequest, row["id"])
    saved.payload_hash = "invalid"
    db.commit()
    assert auth.get(url).status_code == 409
    from app.services.collection_conditions import snapshot_hash

    saved.payload_hash = snapshot_hash(saved.snapshot)
    db.delete(job)
    db.commit()
    assert auth.get(url).status_code == 409


def test_summary_viewer_other_project_and_partial(auth, db, sample, users):
    project, _, _ = sample
    row = auth.post(
        f"/api/projects/{project.id}/collection-conditions",
        json=payload(
            [condition("WANT")],
            requested_count=1,
            requested_count_explicit=True,
        ),
    ).json()
    db.add(Company(project_id=project.id, company_name="別の候補", source="csv"))
    db.commit()
    url = f"/api/collection-conditions/{row['id']}/summary"
    partial = auth.get(url + "?limit=1").json()
    assert partial["total_candidates"] == 2 and partial["counts"]["MATCH"] == 1
    assert partial["shortfall"] is None and partial["target_met"] is None
    full = auth.get(url).json()
    assert full["counts"]["MATCH"] == 2 and full["shortfall"] == 0 and full["target_met"]
    original = db.scalar(select(Company).where(Company.project_id == project.id))
    db.add(
        Company(
            project_id=project.id,
            company_name="登録済み重複",
            source="csv",
            duplicate_of_id=original.id,
        )
    )
    db.commit()
    full = auth.get(url).json()
    assert full["total_candidates"] == 3
    assert full["counts"]["MATCH"] == 2 and full["excluded_duplicate_count"] == 1
    project.user_id = users[1].id
    db.commit()
    assert auth.get(url).status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(url).status_code == 200
