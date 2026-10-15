"""Synthetic historical feedback on the dedicated _test DB; no live requests."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import Activity, FeedbackEvaluation, SiteIdentityReviewEvent
from app.services.collection_feedback import PREFIX as COLLECTION
from app.services.feedback_provenance import digest
from app.services.field_feedback import PREFIX as FIELD
from app.services.field_feedback import capture_web
from offline_replay.feedback import normalize
from tests.test_form_intelligence import make_company
from tests.test_site_identity_review import fixture

START = datetime(2026, 10, 12, tzinfo=timezone.utc)
END = START + timedelta(days=1)
OLD = START - timedelta(days=30)
PARAMS = {"start": START.isoformat(), "end": END.isoformat()}


def collection(company, actor, observed, created=OLD):
    return Activity(
        company_id=company.id,
        activity_type="note",
        created_at=created,
        note=COLLECTION
        + json.dumps(
            {
                "project_id": str(company.project_id),
                "company_id": str(company.id),
                "actor_user_id": str(actor),
                "subject": "company",
                "outcome": "OK",
                "reason": "confirmed",
                "reviewed_at": observed,
            }
        ),
    )


def diagnostic(company, observed):
    snapshot = {
        "form_url": "https://synthetic.example/contact",
        "form_status": "ERROR",
        "safety_blocked": True,
    }
    return Activity(
        company_id=company.id,
        activity_type="note",
        created_at=OLD,
        note=FIELD
        + json.dumps(
            {
                "kind": "FORM_DIAGNOSTIC",
                "project_id": str(company.project_id),
                "company_id": str(company.id),
                "observed_at": observed,
                "snapshot": snapshot,
                "snapshot_hash": digest(snapshot),
                "versions": {},
                "analysis_version": "synthetic",
                "provider": "STATIC",
                "duration_ms": 0,
            }
        ),
    )


def test_large_history_filters_event_time_before_limit_and_evaluation_save(
    auth, db, users, monkeypatch
):
    _, company = make_company(auth, db)
    db.add_all([collection(company, users[0].id, OLD.isoformat()) for _ in range(1001)])
    inside = collection(company, users[0].id, "2026-10-12T09:00:00+09:00")
    db.add_all(
        [
            inside,
            collection(company, users[0].id, (END - timedelta(microseconds=1)).isoformat()),
            collection(company, users[0].id, END.isoformat()),
        ]
    )
    db.commit()
    base = f"/api/projects/{company.project_id}"
    count = db.scalar(select(func.count()).select_from(Activity))
    assert auth.get(base + "/feedback-export").status_code == 413
    response = auth.get(base + "/feedback-export", params=PARAMS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    exported = response.json()
    assert len(exported["records"]) == 2
    assert any(r["source_id"] == str(inside.id) for r in exported["records"])
    assert exported["period"] == {
        "start_inclusive": START.isoformat(),
        "end_exclusive": END.isoformat(),
    }
    assert len(normalize(exported, str(company.project_id))) == 2
    assert db.scalar(select(func.count()).select_from(Activity)) == count
    users[0].is_admin = True
    db.commit()
    monkeypatch.setattr(settings, "feedback_workbench_enabled", True)
    saved = auth.post(base + "/feedback-evaluations", json=PARAMS)
    assert saved.status_code == 200
    assert saved.json()["report"]["review_events"] == 2
    assert saved.json()["report"]["runtime_applied"] is False
    analyzed = auth.post(base + "/feedback-proposals/analyze", json=PARAMS)
    assert analyzed.status_code == 200
    assert analyzed.json()["event_count"] == 2
    assert analyzed.json()["period"] == exported["period"]
    assert analyzed.json()["api_calls"] == 0 and analyzed.json()["runtime_applied"] is False
    assert auth.post(base + "/feedback-proposals/analyze").status_code == 413
    assert db.scalar(select(func.count()).select_from(Activity)) == count


def test_field_history_and_non_events_do_not_consume_period_limit(auth, db):
    _, company = make_company(auth, db)
    db.add_all([diagnostic(company, OLD.isoformat()) for _ in range(1001)])
    db.add_all(
        [
            Activity(
                company_id=company.id,
                activity_type="note",
                note=FIELD
                + json.dumps(
                    {
                        "kind": "WEB_DECISION",
                        "project_id": str(company.project_id),
                        "company_id": str(company.id),
                    }
                ),
            )
            for _ in range(1001)
        ]
    )
    db.add_all([diagnostic(company, START.isoformat()), diagnostic(company, END.isoformat())])
    db.commit()
    base = f"/api/projects/{company.project_id}/feedback-export"
    assert auth.get(base).status_code == 413
    response = auth.get(base, params=PARAMS)
    assert response.status_code == 200
    rows = response.json()["records"]
    assert len(rows) == 1 and rows[0]["source"] == "form_diagnostic"
    assert normalize(response.json(), str(company.project_id))[0]["human"] is False


def test_site_reviews_select_companion_by_id_even_when_inserted_outside_period(
    auth, db, monkeypatch
):
    company, path, body = fixture(auth, db)
    monkeypatch.setattr(settings, "feedback_provenance_enabled", True)
    company.scraped_at = OLD
    capture_web(db, company)
    db.commit()
    assert auth.post(path, json=body).status_code == 201
    row = db.scalar(select(SiteIdentityReviewEvent))
    review_start = row.created_at
    review_end = review_start + timedelta(seconds=1)
    db.add_all(
        [
            SiteIdentityReviewEvent(
                project_id=row.project_id,
                company_id=row.company_id,
                actor_user_id=row.actor_user_id,
                version=i + 2,
                event_type=row.event_type,
                identity_hash=row.identity_hash,
                source_url=row.source_url,
                observed_name=row.observed_name,
                observed_address=row.observed_address,
                observed_phone=row.observed_phone,
                evidence_excerpt=row.evidence_excerpt,
                reasons=row.reasons,
                created_at=OLD,
                expires_at=OLD + timedelta(days=7),
            )
            for i in range(1001)
        ]
    )
    companion = db.scalar(
        select(Activity).where(
            Activity.note.startswith(FIELD), Activity.note.contains('"kind": "SITE_REVIEW"')
        )
    )
    companion.created_at = review_end + timedelta(days=1)
    original = company.website_url
    company.website_url = "https://changed.synthetic.example/"
    db.commit()
    response = auth.get(
        f"/api/projects/{company.project_id}/feedback-export",
        params={"start": review_start.isoformat(), "end": review_end.isoformat()},
    )
    assert response.status_code == 200
    rows = response.json()["records"]
    assert len(rows) == 1 and rows[0]["prediction"] == original
    assert rows[0]["reviewed_official_url"] == original
    db.add(Activity(company_id=company.id, activity_type="note", note=companion.note))
    db.commit()
    assert (
        auth.get(
            f"/api/projects/{company.project_id}/feedback-export",
            params={"start": review_start.isoformat(), "end": review_end.isoformat()},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("bad", ["2026-02-30T00:00:00Z", "2026-10-12T00:00:00", "invalid", None])
def test_unknown_times_fail_closed_not_partial_success(auth, db, users, monkeypatch, bad):
    _, company = make_company(auth, db)
    db.add(collection(company, users[0].id, bad))
    db.commit()
    base = f"/api/projects/{company.project_id}"
    assert auth.get(base + "/feedback-export", params=PARAMS).status_code == 409
    users[0].is_admin = True
    db.commit()
    monkeypatch.setattr(settings, "feedback_workbench_enabled", True)
    assert auth.post(base + "/feedback-evaluations", json=PARAMS).status_code == 409
    assert db.scalar(select(func.count()).select_from(FeedbackEvaluation)) == 0
    assert auth.post(base + "/feedback-proposals/analyze", json=PARAMS).status_code == 409


def test_combined_limit_and_invalid_period_and_owner_boundary(auth, client, db, users, monkeypatch):
    _, company = make_company(auth, db)
    db.add_all([collection(company, users[0].id, START.isoformat()) for _ in range(500)])
    diagnostics = [diagnostic(company, START.isoformat()) for _ in range(501)]
    db.add_all(diagnostics)
    db.commit()
    path = f"/api/projects/{company.project_id}/feedback-export"
    assert auth.get(path, params=PARAMS).status_code == 413
    users[0].is_admin = True
    db.commit()
    with monkeypatch.context() as context:
        context.setattr(settings, "feedback_workbench_enabled", True)
        analysis_path = f"/api/projects/{company.project_id}/feedback-proposals/analyze"
        assert auth.post(analysis_path, json=PARAMS).status_code == 413
        for invalid in [
            {"start": START.isoformat()},
            {**PARAMS, "end": START.isoformat()},
            {**PARAMS, "start": "2026-10-12T00:00:00"},
            {**PARAMS, "project_id": str(company.project_id)},
        ]:
            assert auth.post(analysis_path, json=invalid).status_code == 422
    db.delete(diagnostics[-1])  # Synthetic fixture only; production export remains read-only.
    db.commit()
    exact_limit = auth.get(path, params=PARAMS)
    assert exact_limit.status_code == 200 and len(exact_limit.json()["records"]) == 1000
    for params in [
        {"start": START.isoformat()},
        {**PARAMS, "end": START.isoformat()},
        {**PARAMS, "start": "2026-10-12T00:00:00"},
    ]:
        assert auth.get(path, params=params).status_code == 422
    assert auth.get(
        path, params=PARAMS, headers={"Authorization": "Bearer agent-only-test"}
    ).status_code in {401, 403}
    from tests.conftest import PASSWORD

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert client.get(path, params=PARAMS).status_code == 404


@pytest.mark.parametrize("prefix", [COLLECTION, FIELD])
def test_malformed_json_does_not_raise_database_cast_error(auth, db, prefix):
    _, company = make_company(auth, db)
    db.add(Activity(company_id=company.id, activity_type="note", note=prefix + '{"broken":'))
    db.commit()
    response = auth.get(f"/api/projects/{company.project_id}/feedback-export", params=PARAMS)
    assert response.status_code == 409
