from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from app import worker
from app.models import Company, FormAnalysisLog, OperationJob
from app.services.form_intelligence import analyzer
from app.services.form_intelligence.compatibility import assess_delivery_compatibility
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_intelligence.providers import (
    AmbiguousField,
    DecisionBatch,
    DecisionContext,
    FieldDecision,
    FormDecisionError,
    JevFormDecisionProvider,
)
from app.services.form_intelligence.rules import dom_mapping, rule_mapping
from app.services.scraper import FetchedPage, ScrapeError


def make_company(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "フォーム解析テスト",
            "target_profile_id": profile_id,
            "sales_objective": "OEM事業提携",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://form-intelligence.example"]},
    )
    company_id = auth.get(f"/api/projects/{project['id']}/companies").json()[0]["id"]
    company = db.get(Company, company_id)
    return project, company


class FakeFetcher:
    pages: dict[str, str] = {}

    def fetch_html(self, url: str):
        normalized = url.rstrip("/")
        if normalized not in self.pages:
            raise ScrapeError("ページが見つかりません。")
        return FetchedPage(normalized, self.pages[normalized])

    def close(self):
        pass


def install_pages(monkeypatch, pages):
    FakeFetcher.pages = pages
    monkeypatch.setattr(analyzer, "SafeFetcher", FakeFetcher)
    monkeypatch.setattr(analyzer, "get_form_decision_provider", lambda: None)


def login_as(client, user):
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "test-only-long-password"},
    )
    assert response.status_code == 200


def test_analyze_form_profile_and_manual_correction(auth, db, monkeypatch):
    project, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": (
                '<html><a href="/contact">お問い合わせ</a></html>'
            ),
            "https://form-intelligence.example/contact": """
                <html><body><h1>お問い合わせ</h1>
                <form method="post" action="/contact/send">
                  <label for="company">貴社名</label>
                  <input id="company" name="corporation" required>
                  <label for="email">メールアドレス</label>
                  <input id="email" name="reply_to" type="email" required>
                  <label for="kind">お問い合わせ種別</label>
                  <select id="kind" name="kind" required>
                    <option value="product">商品について</option>
                    <option value="partner">事業提携</option>
                  </select>
                  <label for="body">お問い合わせ内容</label>
                  <textarea id="body" name="body" required></textarea>
                  <button type="submit">送信する</button>
                </form></body></html>
            """,
        },
    )

    response = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze")
    assert response.status_code == 200
    profiles = response.json()
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["form_status"] == "READY"
    assert profile["sales_contact_status"] == "ALLOWED"
    assert profile["captcha_type"] == "CAPTCHA_NONE"
    assert profile["confirmation_page"] is False
    assert profile["review_reason"] == ""
    assert profile["is_primary"] is True
    fields = {item["name"]: item for item in profile["fields"]}
    assert fields["corporation"]["mapped_key"] == "company_name"
    assert fields["reply_to"]["mapped_key"] == "email"
    assert fields["kind"]["mapped_key"] == "contact_category"
    assert fields["kind"]["recommended_value"] == "partner"
    assert fields["body"]["mapped_key"] == "message"

    summaries = auth.get(f"/api/projects/{project['id']}/form-profiles/summary")
    assert summaries.status_code == 200
    assert summaries.json()[0]["form_status"] == "READY"

    corrected = auth.patch(
        f"/api/form-profile-fields/{fields['corporation']['id']}",
        json={
            "mapped_key": "contact_name",
            "recommended_value": "営業担当",
            "reason": "サイト固有の項目",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["decision_source"] == "MANUAL"
    assert corrected.json()["mapped_key"] == "contact_name"
    log = db.scalar(select(FormAnalysisLog).where(FormAnalysisLog.event_type == "manual_corrected"))
    assert log and log.details["before"]["mapped_key"] == "company_name"
    FakeFetcher.pages["https://form-intelligence.example/contact"] = FakeFetcher.pages[
        "https://form-intelligence.example/contact"
    ].replace('name="body"', 'name="inquiry_body"')
    changed = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    assert changed["form_status"] == "STALE"
    changed_fields = {item["name"]: item for item in changed["fields"]}
    assert changed_fields["corporation"]["mapped_key"] == "contact_name"
    assert changed_fields["corporation"]["recommended_value"] == "営業担当"
    assert changed_fields["corporation"]["decision_source"] == "MANUAL"


def test_manual_unknown_body_stays_review_after_reanalysis(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": '<a href="/contact">Contact</a>',
            "https://form-intelligence.example/contact": (
                '<form method="post"><textarea name="message" required></textarea>'
                '<button type="submit">送信</button></form>'
            ),
        },
    )
    profile = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    field = next(f for f in profile["fields"] if f["name"] == "message")
    response = auth.patch(
        f"/api/form-profile-fields/{field['id']}",
        json={
            "mapped_key": "unknown",
            "reason": "入力先を確定できない",
        },
    )
    assert response.status_code == 200
    refreshed = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    assert refreshed["form_status"] == "REVIEW_REQUIRED"
    assert next(f for f in refreshed["fields"] if f["name"] == "message")["mapped_key"] == "unknown"


def test_ai_receives_only_ambiguous_fields_and_cannot_override_rule_results(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": '<a href="/contact">お問い合わせ</a>',
            "https://form-intelligence.example/contact": """
                <form method="post" action="/contact/send">
                  <input name="email" type="email" required>
                  <input name="custom_code" aria-label="識別符号" required>
                  <textarea name="message" required></textarea>
                  <button type="submit">送信</button>
                </form>
            """,
        },
    )

    class CaptureProvider:
        name = "openai"
        contexts = []

        def decide(self, context):
            self.contexts.append(context)
            return DecisionBatch(
                decisions=[
                    FieldDecision(0, "phone", 0.99),
                    FieldDecision(1, "department", 0.92),
                ],
                provider="openai",
                duration_ms=12,
                usage={"input_tokens": 20, "output_tokens": 8},
            )

    provider = CaptureProvider()
    monkeypatch.setattr(analyzer, "get_form_decision_provider", lambda: provider)
    profile = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]

    assert len(provider.contexts) == 1
    assert [(item.position, item.name) for item in provider.contexts[0].fields] == [
        (1, "custom_code")
    ]
    fields = {item["name"]: item for item in profile["fields"]}
    assert fields["email"]["mapped_key"] == "email"
    assert fields["email"]["decision_source"] == "DOM"
    assert fields["custom_code"]["mapped_key"] == "department"
    assert fields["custom_code"]["decision_source"] == "OPENAI"
    requested = db.scalar(
        select(FormAnalysisLog).where(FormAnalysisLog.event_type == "ai_decision_requested")
    )
    completed = db.scalar(
        select(FormAnalysisLog).where(FormAnalysisLog.event_type == "ai_decision_completed")
    )
    assert requested and requested.details["field_count"] == 1
    assert completed and completed.usage["input_tokens"] == 20


def test_jev_provider_remains_a_non_network_placeholder():
    context = DecisionContext(
        sales_objective="事業提携",
        page_text="お問い合わせ",
        fields=[AmbiguousField(0, "識別符号", "custom_code", "text", True)],
    )
    with pytest.raises(FormDecisionError, match="接続仕様が設定されていません"):
        JevFormDecisionProvider().decide(context)


def test_multiple_forms_are_saved_and_primary_can_be_selected(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": '<a href="/contact">お問い合わせ</a>',
            "https://form-intelligence.example/contact": """
                <form method="post" action="/partner">
                  <input name="email" type="email" required>
                  <textarea name="message" required></textarea>
                  <button type="submit">提携相談を送信</button>
                </form>
                <form method="post" action="/support">
                  <input name="email" type="email" required>
                  <textarea name="message" required></textarea>
                  <button type="submit">サポートへ送信</button>
                </form>
            """,
        },
    )
    profiles = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()
    assert len(profiles) == 2
    assert {item["form_index"] for item in profiles} == {0, 1}
    assert sum(item["is_primary"] for item in profiles) == 1

    secondary = next(item for item in profiles if not item["is_primary"])
    selected = auth.post(f"/api/form-profiles/{secondary['id']}/select-primary")
    assert selected.status_code == 200 and selected.json()["is_primary"] is True
    saved = auth.get(f"/api/companies/{company.id}/form-profiles").json()
    assert sum(item["is_primary"] for item in saved) == 1
    assert next(item for item in saved if item["is_primary"])["id"] == secondary["id"]


@pytest.mark.parametrize(
    "prohibition",
    ["営業目的のお問い合わせはご遠慮ください。", "＊セールスはお断りさせていただきます。"],
)
def test_prohibition_captcha_and_fingerprint_change(auth, db, monkeypatch, prohibition):
    _, company = make_company(auth, db)
    root = '<html><a href="/contact">Contact</a></html>'
    first_form = f"""
        <html><body><p>{prohibition}</p>
        <form><label for="message">内容</label>
        <textarea id="message" name="message" required></textarea>
        <div class="g-recaptcha"></div><button type="submit">確認</button></form></body></html>
    """
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": root,
            "https://form-intelligence.example/contact": first_form,
        },
    )
    first = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    assert first["form_status"] == "BLOCKED"
    assert first["sales_contact_status"] == "PROHIBITED"
    assert first["captcha_type"] == "CAPTCHA_RECAPTCHA"
    assert first["confirmation_page"] is True
    original_fingerprint = first["fingerprint"]

    FakeFetcher.pages["https://form-intelligence.example/contact"] = first_form.replace(
        'name="message"', 'name="inquiry_message"'
    )
    second = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    assert second["form_status"] == "BLOCKED"
    assert second["fingerprint"] != original_fingerprint


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ('<div class="h-captcha"></div>', "CAPTCHA_HCAPTCHA"),
        ('<div class="cf-turnstile"></div>', "CAPTCHA_TURNSTILE"),
        ('<div class="g-recaptcha"></div>', "CAPTCHA_RECAPTCHA"),
        ("<label>画像認証</label>", "CAPTCHA_OTHER"),
        ("<form><input name=message></form>", "CAPTCHA_NONE"),
    ],
)
def test_supported_captcha_markers(markup, expected):
    assert analyzer._captcha_type(markup) == expected


def test_form_intelligence_project_access_roles(auth, db, users, monkeypatch):
    project, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": '<a href="/contact">お問い合わせ</a>',
            "https://form-intelligence.example/contact": """
                <form method="post" action="/send">
                  <input name="email" type="email" required>
                  <textarea name="message" required></textarea>
                  <button type="submit">送信</button>
                </form>
            """,
        },
    )
    profile = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    field_id = profile["fields"][0]["id"]
    correction = {
        "mapped_key": "email",
        "recommended_value": "",
        "reason": "権限テスト",
    }
    job = {"company_ids": [str(company.id)], "force": False}

    login_as(auth, users[1])
    assert auth.get(f"/api/projects/{project['id']}/form-profiles/summary").status_code == 404
    assert auth.get(f"/api/companies/{company.id}/form-profiles").status_code == 404
    assert auth.get(f"/api/form-profiles/{profile['id']}").status_code == 404
    assert auth.get(f"/api/form-profiles/{profile['id']}/logs").status_code == 404
    assert auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").status_code == 404
    assert auth.patch(f"/api/form-profile-fields/{field_id}", json=correction).status_code == 404
    assert auth.post(f"/api/form-profiles/{profile['id']}/select-primary").status_code == 404
    assert (
        auth.post(f"/api/projects/{project['id']}/form-intelligence/jobs", json=job).status_code
        == 404
    )

    login_as(auth, users[0])
    assert (
        auth.post(
            f"/api/projects/{project['id']}/members",
            json={"email": users[1].email, "role": "viewer"},
        ).status_code
        == 201
    )
    login_as(auth, users[1])
    assert auth.get(f"/api/projects/{project['id']}/form-profiles/summary").status_code == 200
    assert auth.get(f"/api/companies/{company.id}/form-profiles").status_code == 200
    assert auth.get(f"/api/form-profiles/{profile['id']}").status_code == 200
    assert auth.get(f"/api/form-profiles/{profile['id']}/logs").status_code == 200
    assert auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").status_code == 404
    assert auth.patch(f"/api/form-profile-fields/{field_id}", json=correction).status_code == 404
    assert auth.post(f"/api/form-profiles/{profile['id']}/select-primary").status_code == 404
    assert (
        auth.post(f"/api/projects/{project['id']}/form-intelligence/jobs", json=job).status_code
        == 404
    )

    login_as(auth, users[0])
    assert (
        auth.post(
            f"/api/projects/{project['id']}/members",
            json={"email": users[1].email, "role": "editor"},
        ).status_code
        == 201
    )
    login_as(auth, users[1])
    analyzed = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze")
    assert analyzed.status_code == 200
    latest_field_id = analyzed.json()[0]["fields"][0]["id"]
    assert (
        auth.patch(f"/api/form-profile-fields/{latest_field_id}", json=correction).status_code
        == 200
    )


def test_bulk_form_intelligence_job(auth, db, monkeypatch):
    project, company = make_company(auth, db)
    response = auth.post(
        f"/api/projects/{project['id']}/form-intelligence/jobs",
        json={"company_ids": [str(company.id)], "force": False},
    )
    assert response.status_code == 202
    job = db.get(OperationJob, response.json()["id"])
    assert job.operation_type == "form_intelligence"
    assert job.payload["company_ids"] == [str(company.id)]
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "sync_inbound_mail", lambda _db: 0)
    monkeypatch.setattr(
        worker,
        "analyze_company_forms",
        lambda *_args, **_kwargs: [SimpleNamespace(form_status="READY")],
    )
    assert worker.run_once()
    db.refresh(job)
    assert job.status == "completed" and job.success_count == 1


def test_review_reason_is_saved_for_browser_only_form(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    install_pages(
        monkeypatch,
        {
            "https://form-intelligence.example": '<a href="/contact">お問い合わせ</a>',
            "https://form-intelligence.example/contact": """
                <form method="get">
                  <input name="email" type="email" required>
                  <textarea name="message" required></textarea>
                  <button type="submit">送信する</button>
                </form>
            """,
        },
    )
    profile = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    assert profile["form_status"] == "REVIEW_REQUIRED"
    assert "POST形式" in profile["review_reason"]


def test_fingerprint_is_stable_and_sensitive_to_structure():
    fields = [
        {
            "position": 0,
            "name": "email",
            "element_id": "mail",
            "label": "メールアドレス",
            "field_type": "email",
            "required": True,
            "options": [],
        }
    ]
    assert form_fingerprint(fields) == form_fingerprint([dict(fields[0])])
    changed = [dict(fields[0], required=False)]
    assert form_fingerprint(fields) != form_fingerprint(changed)


def test_delivery_compatibility_reports_browser_only_forms():
    def assess(markup: str):
        form = BeautifulSoup(markup, "html.parser").select_one("form")
        return assess_delivery_compatibility(form, "https://example.com/contact")

    assert assess('<form method="post"><input name="email"><button>送信</button></form>').supported
    assert "POST" in assess('<form><input name="email"></form>').reason
    assert (
        "ファイル"
        in assess(
            '<form method="post" enctype="multipart/form-data">'
            '<input name="file" type="file"></form>'
        ).reason
    )
    assert (
        "外部サイト"
        in assess(
            '<form method="post" action="https://other.example/send"><input name="email"></form>'
        ).reason
    )
    assert "name属性" in assess('<form method="post"><input type="text"></form>').reason


def test_field_mapping_prefers_specific_labels_and_common_names():
    assert rule_mapping("お名前", "text")[0] == "contact_name"
    assert rule_mapping("会社名", "text")[0] == "company_name"
    assert dom_mapping("text", "mail")[0] == "email"
    assert dom_mapping("text", "corporate")[0] == "company_name"
