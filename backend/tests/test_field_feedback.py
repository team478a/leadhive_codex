"""Synthetic frozen field records. No network, approvals or outbound sends."""

import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.config import settings
from app.models import Activity, ApprovalRequest, EmailDelivery, FormDelivery, FormProfile
from app.services import web_analysis
from app.services.field_feedback import PREFIX, bound_web, capture_web
from app.services.scraper import FetchedPage, PageData
from offline_replay.feedback import normalize
from tests.test_collection_feedback import body
from tests.test_form_intelligence import install_pages, make_company
from tests.test_site_identity_review import fixture


def test_site_review_keeps_original_after_url_change_and_revoke(auth, db, monkeypatch):
    company, path, review_body = fixture(auth, db)
    monkeypatch.setattr(settings, "feedback_provenance_enabled", True)
    company.scraped_at = datetime.now(timezone.utc)
    capture_web(db, company)
    db.commit()
    assert auth.post(path, json=review_body).status_code == 201
    original_url = company.website_url
    company.website_url = "https://different.example/"
    db.commit()
    assert auth.post(path + "/revoke", json={"expected_review_version": 1}).status_code == 201
    count = db.scalar(select(func.count()).select_from(Activity))
    export = auth.get(f"/api/projects/{company.project_id}/feedback-export").json()
    records = normalize(export, str(company.project_id))
    assert records[0]["prediction"] == original_url
    assert records[0]["human_value"] == original_url
    assert records[1]["human_value"] is None
    assert records[1]["prediction"] is None  # Changed entity/input cannot reuse old decision.
    assert all(records[0]["versions"][k] for k in ("rule", "code"))
    assert records[0]["versions"]["model"] is None
    assert company.company_name not in json.dumps(export)
    assert db.scalar(select(func.count()).select_from(Activity)) == count
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_legacy_site_review_does_not_invent_historical_url(auth, db):
    company, path, review_body = fixture(auth, db)
    assert auth.post(path, json=review_body).status_code == 201
    export = auth.get(f"/api/projects/{company.project_id}/feedback-export").json()
    row = normalize(export, str(company.project_id))[0]
    assert row["prediction"] is None and row["human_value"] is None
    assert all(v is None for v in row["versions"].values())


def test_web_hook_and_contact_correction_have_bound_versions(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    monkeypatch.setattr(settings, "feedback_provenance_enabled", True)
    monkeypatch.setattr(
        web_analysis,
        "scrape_company",
        lambda *a, **k: (
            FetchedPage(company.website_url, "<html>synthetic</html>"),
            PageData(contact_url="https://form-intelligence.example/contact"),
        ),
    )
    web_analysis.analyze(db, company)
    assert bound_web(db, company)
    request = body(company, outcome="CORRECTED", reason="wrong_destination")
    request["corrected_url"] = "https://form-intelligence.example/inquiry"
    assert (
        auth.post(f"/api/companies/{company.id}/collection-feedback", json=request).status_code
        == 201
    )
    export = auth.get(f"/api/projects/{company.project_id}/feedback-export").json()
    row = normalize(export, str(company.project_id))[0]
    assert row["prediction"].endswith("/contact")
    assert row["human_value"].endswith("/inquiry")
    assert row["versions"]["code"] and row["versions"]["model"] is None
    assert bound_web(db, company) is None


def test_form_snapshot_is_system_and_keeps_old_diagnostic(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    monkeypatch.setattr(settings, "feedback_provenance_enabled", True)
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": (
                '<form method="post"><textarea name="message" required></textarea></form>'
            ),
        },
    )
    assert auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").status_code == 200
    response = auth.get(f"/api/projects/{company.project_id}/feedback-export")
    export = response.json()
    rows = normalize(export, str(company.project_id))
    assert rows and all(not row["human"] and row["human_value"] is None for row in rows)
    assert all(row["field"] == "form_analysis" for row in rows)
    assert all(row["versions"]["code"] for row in rows)
    assert "textarea" not in response.text and "recommended_value" not in response.text
    assert all(row["snapshot"]["safety_blocked"] for row in rows)
    profile = db.scalar(select(FormProfile).where(FormProfile.company_id == company.id))
    profile.form_status = "ERROR"
    db.commit()
    assert auth.get(f"/api/projects/{company.project_id}/feedback-export").json() == export
    assert (
        auth.post(
            f"/api/companies/{company.id}/activities",
            json={
                "activity_type": "note",
                "note": PREFIX + "{}",
            },
        ).status_code
        == 422
    )
    event = db.scalar(
        select(Activity).where(
            Activity.note.startswith(PREFIX), Activity.note.contains('"kind": "FORM_DIAGNOSTIC"')
        )
    )
    corrupted = json.loads(event.note[len(PREFIX) :])
    corrupted["snapshot"]["form_status"] = "READY"
    corrupted["snapshot"]["fingerprint"] = "changed"
    event.note = PREFIX + json.dumps(corrupted)
    db.commit()
    assert auth.get(f"/api/projects/{company.project_id}/feedback-export").status_code == 409


def test_flag_off_and_secret_urls(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    monkeypatch.setattr(settings, "feedback_provenance_enabled", False)
    company.scraped_at = datetime.now(timezone.utc)
    capture_web(db, company)
    db.commit()
    assert bound_web(db, company) is None
    monkeypatch.setattr(settings, "feedback_provenance_enabled", True)
    company.contact_url = "https://example.com/?api_key=never-export-this"
    capture_web(db, company)
    db.commit()
    value = bound_web(db, company)
    assert value["contact_url"] is None and "never-export-this" not in json.dumps(value)
