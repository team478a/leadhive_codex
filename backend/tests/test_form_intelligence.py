from contextlib import nullcontext
from types import SimpleNamespace

from sqlalchemy import select

from app import worker
from app.models import Company, FormAnalysisLog, OperationJob
from app.services.form_intelligence import analyzer
from app.services.form_intelligence.fingerprint import form_fingerprint
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
    log = db.scalar(
        select(FormAnalysisLog).where(FormAnalysisLog.event_type == "manual_corrected")
    )
    assert log and log.details["before"]["mapped_key"] == "company_name"
    FakeFetcher.pages["https://form-intelligence.example/contact"] = FakeFetcher.pages[
        "https://form-intelligence.example/contact"
    ].replace('name="body"', 'name="inquiry_body"')
    changed = auth.post(f"/api/companies/{company.id}/form-intelligence/analyze").json()[0]
    assert changed["form_status"] == "STALE"


def test_prohibition_captcha_and_fingerprint_change(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    root = '<html><a href="/contact">Contact</a></html>'
    first_form = """
        <html><body><p>営業目的のお問い合わせはご遠慮ください。</p>
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
