from datetime import datetime, timedelta, timezone

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select, text

from app.models import Company, FormAnalysisLog, FormProfile, FormProfileField, ProjectMember
from app.services import form_live_check as live
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.scraper import FetchedPage, ScrapeError

HTML = '<form action="/contact" method="post"><textarea name="body" required></textarea></form>'


def prepare(auth, db):
    target = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "Live check fixture",
            "target_profile_id": target,
            "sales_objective": "Partnership",
            "region": "Tokyo",
            "status": "active",
        },
    ).json()
    company = Company(
        project_id=project["id"],
        company_name="Fixture",
        domain="review.example",
        website_url="https://review.example",
        source="url",
    )
    db.add(company)
    db.flush()
    profile = FormProfile(
        company_id=company.id,
        form_url="https://review.example/contact",
        form_found=True,
        form_status="REVIEW_REQUIRED",
        sales_contact_status="UNCERTAIN",
    )
    db.add(profile)
    db.flush()
    db.add(
        FormProfileField(
            form_profile_id=profile.id,
            position=0,
            name="body",
            field_type="textarea",
            required=True,
            mapped_key="message",
        )
    )
    profile.action_url = profile.form_url
    profile.fingerprint = form_fingerprint(
        parse_form_fields(BeautifulSoup(HTML, "html.parser").form)
    )
    db.commit()
    return project, company, profile


def mock_page(monkeypatch, profile, html=HTML, url=None, failure=False):
    calls = []

    class Fetcher:
        def fetch_html(self, target):
            calls.append(target)
            if failure:
                raise ScrapeError("robots.txtにより解析が許可されていません。")
            return FetchedPage(url or profile.form_url, html)

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(live, "TargetFetcher", Fetcher)
    return calls


@pytest.mark.parametrize(
    "html,status,captcha,prohibited",
    [
        (HTML, "SAME_STRUCTURE", "NOT_DETECTED_STATIC", False),
        (HTML.replace('name="body"', 'name="changed"'), "CHANGED", "NOT_DETECTED_STATIC", False),
        (
            HTML.replace('action="/contact"', 'action="/elsewhere"'),
            "CHANGED",
            "NOT_DETECTED_STATIC",
            False,
        ),
        (HTML.replace('method="post"', 'method="get"'), "CHANGED", "NOT_DETECTED_STATIC", False),
        ("<p>フォームなし</p>", "FORM_NOT_FOUND", "NOT_DETECTED_STATIC", False),
        (HTML + '<script src="recaptcha.js"></script>', "SAME_STRUCTURE", "DETECTED", False),
        (HTML + "営業メールはご遠慮ください", "SAME_STRUCTURE", "NOT_DETECTED_STATIC", True),
    ],
)
def test_target_diagnostics_and_no_send(auth, db, monkeypatch, html, status, captcha, prohibited):
    _, _, profile = prepare(auth, db)
    saved_hash = profile.fingerprint
    tables = (
        "approval_requests",
        "email_deliveries",
        "form_deliveries",
        "operation_jobs",
        "form_profile_fields",
    )
    before = {
        table: db.execute(text("SELECT row_to_json(t)::text FROM " + table + " t")).scalars().all()
        for table in tables
    }
    calls = mock_page(monkeypatch, profile, html)
    response = auth.post(f"/api/form-profiles/{profile.id}/live-check")
    assert response.status_code == 200
    result = response.json()
    assert result["structure_status"] == status and result["captcha_state"] == captcha
    assert result["sales_prohibition_detected"] is prohibited
    assert not result["execution_allowed"]
    assert calls == [profile.form_url, "closed"]
    db.refresh(profile)
    assert profile.fingerprint == saved_hash and profile.form_status != "READY"
    assert profile.sales_contact_status == ("PROHIBITED" if prohibited else "UNCERTAIN")
    assert not profile.delivery_supported
    assert before == {
        table: db.execute(text("SELECT row_to_json(t)::text FROM " + table + " t")).scalars().all()
        for table in tables
    }
    log = db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.provider == "rule-target-get"))
    assert log.actor_user_id is not None and log.details["operation"] == "target_live_check"
    assert "html" not in log.details
    assert auth.post(f"/api/form-profiles/{profile.id}/live-check").status_code == 429


@pytest.mark.parametrize("failure", [True, False])
def test_failure_or_redirect_preserves_saved_fields(auth, db, monkeypatch, failure):
    _, _, profile = prepare(auth, db)
    mock_page(monkeypatch, profile, url=profile.form_url + "/moved", failure=failure)
    result = auth.post(f"/api/form-profiles/{profile.id}/live-check").json()
    assert result["structure_status"] == ("FETCH_FAILED" if failure else "REDIRECTED")
    db.refresh(profile)
    assert profile.form_status == "STALE" and not profile.delivery_supported


def test_roles_and_project_boundaries_before_network(auth, db, users, monkeypatch):
    project, _, profile = prepare(auth, db)
    calls = mock_page(monkeypatch, profile)
    path = f"/api/form-profiles/{profile.id}/live-check"
    assert auth.post(path, headers={"Authorization": "Bearer agent"}).status_code in (401, 403)
    auth.post("/api/auth/logout")
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.post(path).status_code in (403, 404)
    db.add(ProjectMember(project_id=project["id"], user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.post(path).status_code == 404
    assert calls == []


def test_existing_prohibition_never_cleared(auth, db, monkeypatch):
    _, _, profile = prepare(auth, db)
    profile.sales_contact_status = "PROHIBITED"
    profile.form_status = "BLOCKED"
    db.commit()
    mock_page(monkeypatch, profile)
    assert auth.post(f"/api/form-profiles/{profile.id}/live-check").status_code == 200
    db.refresh(profile)
    assert profile.sales_contact_status == "PROHIBITED" and profile.form_status == "BLOCKED"


def test_redirect_robots_guard(monkeypatch):
    fetcher = live.TargetFetcher()
    try:
        monkeypatch.setattr(fetcher, "robots_allowed", lambda url: False)
        with pytest.raises(ScrapeError, match="robots"):
            fetcher._request("https://public.example/redirect-target", 100, redirects=1)
    finally:
        fetcher.close()


def test_latest_result_is_read_only_and_survives_reopen(auth, db, monkeypatch, users):
    project, _, profile = prepare(auth, db)
    calls = mock_page(monkeypatch, profile)
    path = f"/api/form-profiles/{profile.id}/live-check"
    assert auth.get(path).json() is None
    posted = auth.post(path).json()
    assert posted["freshness"] == "CURRENT" and posted["expires_at"]
    before = (
        db.execute(text("SELECT row_to_json(t)::text FROM form_analysis_logs t")).scalars().all()
    )
    assert auth.get(path).json() == posted
    assert auth.get(path, headers={"Authorization": "Bearer agent"}).status_code in (401, 403)
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=project["id"], user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(path).json() == posted
    assert calls == [profile.form_url, "closed"]
    assert (
        before
        == db.execute(text("SELECT row_to_json(t)::text FROM form_analysis_logs t")).scalars().all()
    )
    assert "source_binding" not in posted


@pytest.mark.parametrize(
    "change,expected",
    [
        ("expired", "EXPIRED"),
        ("fingerprint", "SOURCE_CHANGED"),
        ("url", "SOURCE_CHANGED"),
        ("action", "SOURCE_CHANGED"),
        ("index", "SOURCE_CHANGED"),
        ("invalid", "INVALID"),
        ("future", "INVALID"),
    ],
)
def test_latest_freshness_never_grants_permission(auth, db, monkeypatch, change, expected):
    _, _, profile = prepare(auth, db)
    mock_page(monkeypatch, profile)
    path = f"/api/form-profiles/{profile.id}/live-check"
    assert auth.post(path).status_code == 200
    log = db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.form_profile_id == profile.id))
    if change == "expired":
        log.details = log.details | {
            "checked_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        }
    elif change == "invalid":
        log.details = log.details | {"checked_at": "bad-date"}
    elif change == "future":
        log.details = log.details | {
            "checked_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        }
    elif change == "fingerprint":
        profile.fingerprint = "a" * 64
    elif change == "url":
        profile.form_url += "?private=not-for-response"
    elif change == "action":
        profile.action_url += "?private=not-for-response"
    else:
        profile.form_index += 1
    db.commit()
    result = auth.get(path)
    assert result.json()["freshness"] == expected
    assert not result.json()["execution_allowed"]
    assert "private" not in result.text
    db.refresh(profile)
    assert profile.form_status == "REVIEW_REQUIRED" and profile.sales_contact_status == "UNCERTAIN"


@pytest.mark.parametrize("status", ["STALE", "ERROR", "BLOCKED"])
def test_individual_correction_cannot_clear_invalidated_profile(auth, db, status):
    _, _, profile = prepare(auth, db)
    field = db.scalar(
        select(FormProfileField).where(FormProfileField.form_profile_id == profile.id)
    )
    profile.form_status = status
    profile.review_reason = "現在のサイトの確認が必要"
    db.commit()
    response = auth.patch(
        f"/api/form-profile-fields/{field.id}",
        json={
            "mapped_key": "message",
            "recommended_value": "Stored Human edit",
            "reason": "Correction",
        },
    )
    assert response.status_code == 200
    db.refresh(profile)
    assert profile.form_status == status and not profile.delivery_supported
    assert profile.review_reason == "現在のサイトの確認が必要"
