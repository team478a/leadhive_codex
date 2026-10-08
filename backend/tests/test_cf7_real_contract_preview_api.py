from bs4 import BeautifulSoup
from sqlalchemy import func, select, text

from app import form_intelligence_routes as routes
from app.models import FormAnalysisLog, OutreachDraft, ProjectMember
from app.services import form_live_check as live
from app.services.cf7_static_inspection import inspect_isolated
from app.services.form_execution_plan import PlanError
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from tests.test_cf7_real_contract_preview import page
from tests.test_form_input_preparation import inputs
from tests.test_form_input_preparation_api import setup
from tests.test_form_live_check import mock_page


def test_preview_rebuilds_server_payload_without_writes_or_send(auth, db, users, monkeypatch):
    profile, company = setup(auth, db, users, monkeypatch)
    observation = inputs()[2]
    observation["cf7_static"] = inspect_isolated(page(url=profile.form_url), profile.form_url, 0)
    monkeypatch.setattr(routes, "latest_live_check", lambda *args: observation)
    path = f"/api/form-profiles/{profile.id}"
    assert auth.get(path + "/contract-preview").json()["status"] == "HOLD"
    report = auth.get(path + "/input-preparation").json()
    response = auth.post(
        path + "/input-preparation/reviews",
        json={"expected_snapshot_hash": report["snapshot_hash"], "input_content_confirmed": True},
    )
    assert response.status_code == 200, response.text
    before = db.scalar(select(func.count()).select_from(FormAnalysisLog))
    result = auth.get(path + "/contract-preview")
    assert result.status_code == 200 and result.json()["status"] == "PREVIEW_ONLY", result.text
    assert result.json()["contract"]["company_id"] == str(company.id)
    assert not result.json()["execution_allowed"]
    assert result.json()["encoding_preview"]["wire_size"] > 0
    assert not result.json()["encoding_preview"]["execution_allowed"]
    assert "body" not in result.json()["encoding_preview"]
    original_encoder = routes.encode_real_preview

    def fail_encoding(*args, **kwargs):
        raise PlanError("PRIVATE diagnostic")

    monkeypatch.setattr(routes, "encode_real_preview", fail_encoding)
    unsupported = auth.get(path + "/contract-preview")
    assert unsupported.status_code == 200 and unsupported.json()["status"] == "HOLD"
    assert unsupported.json()["reasons"] == ["WIRE_ENCODING_UNSUPPORTED"]
    assert unsupported.json()["encoding_preview"] is None and "PRIVATE" not in unsupported.text
    monkeypatch.setattr(routes, "encode_real_preview", original_encoder)
    assert db.scalar(select(func.count()).select_from(FormAnalysisLog)) == before
    # Query/body fields cannot replace the server snapshot or enable execution.
    assert (
        auth.get(path + "/contract-preview?confirmed=true&execution_allowed=true").json()
        == result.json()
    )
    assert auth.post(path + "/contract-preview", json={"confirmed": True}).status_code == 405
    assert auth.get(
        path + "/contract-preview", headers={"Authorization": "Bearer agent"}
    ).status_code in (401, 403)
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path + "/contract-preview").status_code == 404
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    viewer = auth.get(path + "/contract-preview")
    assert viewer.json()["status"] == "HOLD" and "sender@example.com" not in viewer.text
    auth.post(
        "/api/auth/login", json={"email": users[0].email, "password": "test-only-long-password"}
    )
    draft = db.scalar(select(OutreachDraft).where(OutreachDraft.company_id == company.id))
    draft.body = "Changed"
    db.commit()
    changed = auth.get(path + "/contract-preview").json()
    assert changed["status"] == "HOLD" and changed["contract"] is None
    assert db.scalar(select(func.count()).select_from(FormAnalysisLog)) == before


def test_saved_get_evidence_roundtrip_keeps_execution_tables_unchanged(
    auth, db, users, monkeypatch
):
    profile, _ = setup(auth, db, users, monkeypatch)
    html = page(url=profile.form_url)
    profile.action_url = profile.form_url
    profile.fingerprint = form_fingerprint(
        parse_form_fields(BeautifulSoup(html, "html.parser").form)
    )
    db.commit()
    monkeypatch.setattr(routes, "latest_live_check", live.latest)
    calls = mock_page(monkeypatch, profile, html)
    tables = ("approval_requests", "email_deliveries", "form_deliveries", "operation_jobs")
    counts = {t: db.scalar(text("SELECT count(*) FROM " + t)) for t in tables}
    path = f"/api/form-profiles/{profile.id}"
    result = auth.post(path + "/live-check")
    assert result.status_code == 200 and result.json()["structure_status"] == "SAME_STRUCTURE", (
        result.text
    )
    assert (
        result.json()["cf7_static"]["contract_evidence"]["source_kind"] == "REAL_SITE_STATIC_HTML"
    )
    report = auth.get(path + "/input-preparation").json()
    assert report["can_record"], report
    assert (
        auth.post(
            path + "/input-preparation/reviews",
            json={
                "expected_snapshot_hash": report["snapshot_hash"],
                "input_content_confirmed": True,
            },
        ).status_code
        == 200
    )
    assert auth.get(path + "/contract-preview").json()["status"] == "PREVIEW_ONLY"
    assert calls == [profile.form_url, "closed"]  # GET fixture only; preview never fetches.
    assert counts == {t: db.scalar(text("SELECT count(*) FROM " + t)) for t in tables}
    log = db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.provider == "rule-target-get"))
    assert "PRIVATE DEFAULT" not in str(log.details)
