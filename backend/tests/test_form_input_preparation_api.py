from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app import form_intelligence_routes as routes
from app.models import (
    FormAnalysisLog,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    ProjectMember,
)
from tests.test_form_input_preparation import inputs
from tests.test_form_review_material_api import seed


def setup(auth, db, users, monkeypatch):
    _, company, profile = seed(auth, db)
    users[0].is_admin = True
    profile.captcha_type = "CAPTCHA_NONE"
    profile.fingerprint = "f" * 64
    profile.sales_contact_status = "ALLOWED"
    db.add_all(
        [
            FormSenderSettings(id=1, email="sender@example.com"),
            OutreachDraft(company_id=company.id, channel="form", body="Draft"),
            FormProfileField(
                form_profile_id=profile.id, position=2, name="_wpcf7", field_type="hidden"
            ),
        ]
    )
    db.commit()
    # Stable observation timestamp: each read must represent the same saved observation.
    observation = inputs()[2]
    monkeypatch.setattr(routes, "latest_live_check", lambda *args: observation)
    return profile, company


def test_human_record_is_idempotent_and_draft_change_invalidates(auth, db, users, monkeypatch):
    profile, company = setup(auth, db, users, monkeypatch)
    path = f"/api/form-profiles/{profile.id}/input-preparation"
    report = auth.get(path).json()
    assert report["can_record"]
    payload = {"expected_snapshot_hash": report["snapshot_hash"], "input_content_confirmed": True}
    count = db.scalar(select(func.count()).select_from(FormAnalysisLog))
    for _ in range(2):
        result = auth.post(path + "/reviews", json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["review_status"] == "RECORDED"
        assert not result.json()["eligible_for_approval"]
    assert db.scalar(select(func.count()).select_from(FormAnalysisLog)) == count + 1
    log = db.scalar(
        select(FormAnalysisLog).where(
            FormAnalysisLog.details["operation"].astext == "input_preparation_review"
        )
    )
    assert "Draft" not in str(log.details) and log.actor_user_id == users[0].id
    log.details = log.details | {
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    }
    db.commit()
    assert auth.get(path).json()["review_status"] == "EXPIRED"
    draft = db.scalar(select(OutreachDraft).where(OutreachDraft.company_id == company.id))
    draft.body = "Changed"
    db.commit()
    assert auth.get(path).json()["review_status"] == "INVALIDATED"
    assert auth.post(path + "/reviews", json=payload).status_code == 409


def test_agent_and_wrong_hash_rejected_and_get_is_read_only(auth, db, users, monkeypatch):
    profile, _ = setup(auth, db, users, monkeypatch)
    path = f"/api/form-profiles/{profile.id}/input-preparation"
    before = db.scalar(select(func.count()).select_from(FormAnalysisLog))
    assert auth.get(path).status_code == 200
    assert db.scalar(select(func.count()).select_from(FormAnalysisLog)) == before
    payload = {"expected_snapshot_hash": "0" * 64, "input_content_confirmed": True}
    assert auth.post(path + "/reviews", json=payload).status_code == 409
    assert auth.get(path, headers={"Authorization": "Bearer agent"}).status_code in (401, 403)
    assert auth.post(
        path + "/reviews", json=payload, headers={"Authorization": "Bearer agent"}
    ).status_code in (401, 403)
    assert db.scalar(select(func.count()).select_from(FormAnalysisLog)) == before


def test_other_project_viewer_and_secret_sender_boundary(auth, db, users, monkeypatch):
    profile, company = setup(auth, db, users, monkeypatch)
    path = f"/api/form-profiles/{profile.id}/input-preparation"
    payload = {"expected_snapshot_hash": "0" * 64, "input_content_confirmed": True}
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    response = auth.get(path)
    assert response.status_code == 200
    assert "sender@example.com" not in response.text
    # Existing project write checks hide inaccessible write resources with 404.
    assert auth.post(path + "/reviews", json=payload).status_code == 404
