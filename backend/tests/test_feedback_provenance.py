import json

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import Activity, Company, ProjectMember
from app.services import ai_analysis
from app.services.feedback_provenance import PREFIX, bound_decision
from offline_replay.feedback import normalize
from tests.test_ai import FakeProvider, decision, make_analyzable_company, make_project
from tests.test_collection_feedback import body


def analyzed(auth, db, monkeypatch):
    project = make_project(auth)
    item = make_analyzable_company(auth, db, project["id"])
    monkeypatch.setattr(settings, "feedback_provenance_enabled", True)
    monkeypatch.setattr(ai_analysis, "get_ai_provider", lambda: FakeProvider(decision()))
    assert auth.post(f"/api/companies/{item['id']}/ai-analysis", json={}).status_code == 200
    company = db.get(Company, item["id"])
    return company


def test_capture_and_private_export(auth, db, monkeypatch):
    company = analyzed(auth, db, monkeypatch)
    metadata = bound_decision(db, company)
    assert metadata["prediction"] is True
    assert metadata["raw_ai_is_target"] is False  # Core rank result, not AI's boolean, is used.
    assert all(metadata["versions"].values())
    assert len(metadata["input_hash"]) == 64
    assert "website_text" not in json.dumps(metadata)
    assert (
        auth.post(
            f"/api/companies/{company.id}/collection-feedback",
            json=body(company, subject="company"),
        ).status_code
        == 201
    )
    count = db.scalar(select(func.count()).select_from(Activity))
    response = auth.get(f"/api/projects/{company.project_id}/feedback-export")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    export = response.json()
    normalized = normalize(export, str(company.project_id))
    assert normalized[0]["prediction"] is True and normalized[0]["human_value"] is True
    assert normalized[0]["versions"]["model"] == "fake-v1"
    assert "企業向け採用支援" not in response.text
    assert db.scalar(select(func.count()).select_from(Activity)) == count


def test_stale_binding_and_reserved_prefix(auth, db, monkeypatch):
    company = analyzed(auth, db, monkeypatch)
    company.website_url = "https://different.example/"
    db.commit()
    assert bound_decision(db, company) is None
    assert (
        auth.post(
            f"/api/companies/{company.id}/activities",
            json={"activity_type": "note", "note": PREFIX + "{}"},
        ).status_code
        == 422
    )
    assert (
        auth.post(
            f"/api/companies/{company.id}/collection-feedback",
            json=body(company, subject="company"),
        ).status_code
        == 201
    )
    row = auth.get(f"/api/projects/{company.project_id}/feedback-export").json()["records"][0]
    assert row["prediction"] is None and all(v is None for v in row["versions"].values())


def test_export_owner_only_agent_and_logout(auth, db, users, monkeypatch):
    company = analyzed(auth, db, monkeypatch)
    path = f"/api/projects/{company.project_id}/feedback-export"
    assert auth.get(path, headers={"Authorization": "Bearer agent"}).status_code == 403
    auth.post("/api/auth/logout")
    assert auth.get(path).status_code == 401
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 404
    for role in ("viewer", "editor"):
        member = ProjectMember(project_id=company.project_id, user_id=users[1].id, role=role)
        db.add(member)
        db.commit()
        assert auth.get(path).status_code == 404
        db.delete(member)
        db.commit()


def test_flag_off_and_failed_analysis_has_no_success_event(auth, db, monkeypatch):
    company = analyzed(auth, db, monkeypatch)
    old_count = db.scalar(
        select(func.count()).select_from(Activity).where(Activity.note.startswith(PREFIX))
    )
    monkeypatch.setattr(settings, "feedback_provenance_enabled", False)
    assert (
        auth.post(f"/api/companies/{company.id}/ai-analysis", json={"force": True}).status_code
        == 200
    )
    assert (
        db.scalar(
            select(func.count()).select_from(Activity).where(Activity.note.startswith(PREFIX))
        )
        == old_count
    )


def test_changed_input_unbinds_and_failed_capture_rolls_back(auth, db, monkeypatch):
    company = analyzed(auth, db, monkeypatch)
    company.website_text += " changed"
    db.commit()
    assert bound_decision(db, company) is None
    count = db.scalar(
        select(func.count()).select_from(Activity).where(Activity.note.startswith(PREFIX))
    )

    def failed(*args):
        raise RuntimeError("synthetic metadata failure")

    monkeypatch.setattr(ai_analysis, "record_decision", failed)
    response = auth.post(f"/api/companies/{company.id}/ai-analysis", json={"force": True})
    assert response.json()["ai_status"] == "failed"
    assert (
        db.scalar(
            select(func.count()).select_from(Activity).where(Activity.note.startswith(PREFIX))
        )
        == count
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com/",
        "https://example.com/?key=secret",
        "https://example.com/#secret",
    ],
)
def test_export_does_not_include_url_secrets(url):
    from app.feedback_export_routes import private_safe_url

    assert private_safe_url(url) is None


def test_export_over_limit_is_not_silently_truncated(auth, db, monkeypatch):
    from app.services.collection_feedback import PREFIX as FEEDBACK_PREFIX

    company = analyzed(auth, db, monkeypatch)
    db.add_all(
        [
            Activity(company_id=company.id, activity_type="note", note=FEEDBACK_PREFIX + "{}")
            for _ in range(1001)
        ]
    )
    db.commit()
    assert auth.get(f"/api/projects/{company.project_id}/feedback-export").status_code == 413
