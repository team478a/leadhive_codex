from app.models import Company
from app.services.form_intelligence import analyzer
from app.services.scraper import FetchedPage, ScrapeError


class FakeFetcher:
    def fetch_html(self, url: str):
        normalized = url.rstrip("/")
        if normalized not in self.pages:
            raise ScrapeError("ページが見つかりません。")
        return FetchedPage(normalized, self.pages[normalized])

    def close(self):
        pass


def test_name_email_form_on_contact_anchor_is_detected(auth, db, monkeypatch):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "フォーム誤検出防止テスト",
            "target_profile_id": profile_id,
            "sales_objective": "OEM事業提携",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://contact-analysis.example"]},
    )
    company_id = auth.get(f"/api/projects/{project['id']}/companies").json()[0]["id"]
    company = db.get(Company, company_id)
    assert company is not None

    fetcher = FakeFetcher()
    fetcher.pages = {
        "https://contact-analysis.example": "",
        "https://contact-analysis.example/contact": (
            '<form method="post" action="/send">'
            '<input name="your-name"><input name="your-email" type="email">'
            '<button type="submit">送信</button></form>'
        ),
    }
    monkeypatch.setattr(analyzer, "SafeFetcher", lambda: fetcher)
    monkeypatch.setattr(analyzer, "get_form_decision_provider", lambda: None)

    profiles = auth.post(f"/api/companies/{company_id}/form-intelligence/analyze").json()

    assert len(profiles) == 1
    assert profiles[0]["form_found"] is True
    assert profiles[0]["form_url"] == "https://contact-analysis.example/contact"
    assert profiles[0]["form_status"] == "REVIEW_REQUIRED"
    assert {field["name"] for field in profiles[0]["fields"] if field["name"]} == {
        "your-name",
        "your-email",
    }
