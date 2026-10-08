from uuid import UUID, uuid4

import pytest

from app.models import Company
from app.services import scraper, web_analysis
from app.services.scraper import FetchedPage, PageData, ScrapeError, extract_page

HTML = """
<!doctype html><html><head>
<title>株式会社サンプル | 公式サイト</title>
<meta name="description" content="物流と配送を支援する会社です。">
<meta property="og:site_name" content="株式会社サンプル">
</head><body>
<p>〒530-0001 大阪府大阪市北区梅田1-1-1</p>
<p>TEL: 06-1234-5678</p><a href="mailto:info@example.jp">メール</a>
<a href="/contact">お問い合わせ</a>
<a href="https://instagram.com/sample">Instagram</a>
<a href="https://instagram.com/p/ignored">投稿</a>
<a href="https://x.com/sample">X</a>
<a href="https://twitter.com/intent/tweet">共有</a>
<a href="https://tiktok.com/@sample">TikTok</a>
<a href="https://facebook.com/sample">Facebook</a>
<a href="https://youtube.com/@sample">YouTube</a>
<a href="https://lin.ee/example">LINE</a>
<script>secret script text</script>
</body></html>
"""


def make_project(auth, name="解析テスト"):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    return auth.post(
        "/api/projects",
        json={
            "project_name": name,
            "target_profile_id": profile_id,
            "sales_objective": "解析テスト",
            "region": "大阪府",
            "status": "active",
        },
    ).json()


def add_url(auth, project_id, url):
    response = auth.post(f"/api/projects/{project_id}/collection-jobs/urls", json={"urls": [url]})
    assert response.status_code == 201
    companies = auth.get(f"/api/projects/{project_id}/companies").json()
    return next(item for item in companies if item["website_url"] == url.rstrip("/"))


def test_extract_company_contact_location_and_socials():
    data = extract_page(HTML, "https://example.jp/")
    assert data.company_name == "株式会社サンプル"
    assert data.business_summary == "物流と配送を支援する会社です。"
    assert data.phone == "06-1234-5678"
    assert data.email == "info@example.jp"
    assert data.prefecture == "大阪府" and data.city == "大阪市"
    assert data.contact_url == "https://example.jp/contact"
    assert data.instagram_url == "https://instagram.com/sample"
    assert data.x_url == "https://x.com/sample"
    assert data.tiktok_url == "https://tiktok.com/@sample"
    assert data.facebook_url == "https://facebook.com/sample"
    assert data.youtube_url == "https://youtube.com/@sample"
    assert data.line_url == "https://lin.ee/example"
    assert "secret script text" not in data.website_text


def test_target_validation_blocks_private_network_and_unsafe_urls(monkeypatch):
    monkeypatch.setattr(
        scraper.socket,
        "getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(ScrapeError, match="プライベート"):
        scraper._validated_target("http://example.com")
    with pytest.raises(ScrapeError, match="標準ポート"):
        scraper._validated_target("https://example.com:8443")
    with pytest.raises(ScrapeError, match="認証情報"):
        scraper._validated_target("https://user:pass@example.com")
    monkeypatch.setattr(
        scraper.socket,
        "getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert scraper._validated_target("HTTPS://WWW.Example.COM/?page=1#section")[0] == (
        "https://www.example.com/?page=1"
    )


def test_aggregator_detection_is_domain_exact():
    assert scraper.is_aggregator_domain("www.instagram.com")
    assert scraper.is_aggregator_domain("sub.youtube.com")
    assert not scraper.is_aggregator_domain("instagram.com.example.jp")
    assert not scraper.is_aggregator_domain("example.jp")


def test_robots_rules_are_respected(monkeypatch):
    fetcher = object.__new__(scraper.SafeFetcher)
    monkeypatch.setattr(
        fetcher,
        "_request",
        lambda *args, **kwargs: FetchedPage(
            "https://example.com/robots.txt", "User-agent: *\nDisallow: /private"
        ),
    )
    assert not fetcher.robots_allowed("https://example.com/private/company")
    assert fetcher.robots_allowed("https://example.com/public")


def test_multipage_analysis_discovers_and_merges_important_pages(monkeypatch):
    pages = {
        "https://example.com": """
            <html><head><title>Example</title></head><body>
            <a href="/contact">お問い合わせ</a><a href="/company">会社概要</a>
            <a href="/services">サービス</a><a href="/recruit">採用情報</a>
            <a href="/brochure.pdf">会社案内PDF</a><a href="https://outside.example/about">外部</a>
            </body></html>
        """,
        "https://example.com/contact": (
            "<p>TEL: 03-1111-2222</p>" + "<a href='mailto:sales@example.com'>Mail</a>"
        ),
        "https://example.com/company": "<p>東京都千代田区丸の内1-1-1</p>",
        "https://example.com/services": "<p>法人向け物流支援サービスを提供しています。</p>",
        "https://example.com/recruit": "<a href='https://instagram.com/example'>Instagram</a>",
    }

    class FakeFetcher:
        def fetch_html(self, url):
            return FetchedPage(url, pages[url])

        def close(self):
            pass

    monkeypatch.setattr(scraper, "SafeFetcher", FakeFetcher)
    page, data = scraper.scrape_company("https://example.com")
    assert page.url == "https://example.com"
    assert data.scraped_urls == list(pages)
    assert data.phone == "03-1111-2222" and data.email == "sales@example.com"
    assert data.prefecture == "東京都" and data.city == "千代田区"
    assert data.instagram_url == "https://instagram.com/example"
    assert "法人向け物流支援サービス" in data.website_text
    assert "outside.example" not in data.scraped_urls


def test_company_analysis_success(auth, monkeypatch):
    project = make_project(auth)
    company = add_url(auth, project["id"], "https://original.example")
    monkeypatch.setattr(
        web_analysis,
        "scrape_company",
        lambda url: (
            FetchedPage("https://final.example/", HTML),
            extract_page(HTML, "https://final.example/"),
        ),
    )
    response = auth.post(f"/api/companies/{company['id']}/analyze", json={})
    assert response.status_code == 200
    result = response.json()
    assert result["analysis_status"] == "completed"
    assert result["company_name"] == "株式会社サンプル"
    assert result["domain"] == "final.example"
    assert result["prefecture"] == "大阪府"
    assert result["contact_url"] == "https://final.example/contact"
    assert result["instagram_url"] == "https://instagram.com/sample"
    assert result["website_text"]
    assert result["scraped_urls"] == ["https://final.example/"]
    assert result["scraped_at"]
    assert result["contact_quality_status"] == "observed"
    assert result["contact_source_url"] == "https://final.example/contact"
    assert result["contact_checked_at"]


def test_company_analysis_preserves_and_releases_protected_fields(auth, monkeypatch):
    project = make_project(auth)
    company = add_url(auth, project["id"], "https://protected.example")
    editable = {
        "company_name": "手動の会社名",
        "address": "",
        "prefecture": "",
        "city": "",
        "phone": "03-0000-0000",
        "email": "",
        "contact_url": "https://manual.example/contact",
        "instagram_url": "",
        "x_url": "",
        "tiktok_url": "",
        "facebook_url": "",
        "youtube_url": "",
        "line_url": "",
        "assignee": "",
        "protected_fields": ["company_name", "contact_url"],
    }
    saved = auth.put(f"/api/companies/{company['id']}", json=editable)
    assert saved.status_code == 200
    assert saved.json()["protected_fields"] == ["company_name", "contact_url"]
    invalid = {**editable, "protected_fields": ["website_text"]}
    assert auth.put(f"/api/companies/{company['id']}", json=invalid).status_code == 422
    monkeypatch.setattr(
        web_analysis,
        "scrape_company",
        lambda url: (
            FetchedPage(url, HTML),
            PageData(
                company_name="解析された会社名",
                phone="03-9999-9999",
                contact_url="https://protected.example/contact",
            ),
        ),
    )
    protected = auth.post(f"/api/companies/{company['id']}/analyze", json={"force": True})
    assert protected.json()["company_name"] == "手動の会社名"
    assert protected.json()["contact_url"] == "https://manual.example/contact"
    assert protected.json()["phone"] == "03-9999-9999"

    editable["protected_fields"] = []
    auth.put(f"/api/companies/{company['id']}", json=editable)
    released = auth.post(f"/api/companies/{company['id']}/analyze", json={"force": True})
    assert released.json()["company_name"] == "解析された会社名"
    assert released.json()["contact_url"] == "https://protected.example/contact"


def test_analysis_failure_missing_url_and_aggregator(auth, db, monkeypatch):
    project = make_project(auth)
    csv_content = b"company_name,website_url,phone,email,address\nNo URL,,,,\n"
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/csv",
        files={"file": ("companies.csv", csv_content, "text/csv")},
    )
    companies = auth.get(f"/api/projects/{project['id']}/companies").json()
    missing = next(item for item in companies if item["company_name"] == "No URL")
    result = auth.post(f"/api/companies/{missing['id']}/analyze", json={}).json()
    assert result["analysis_status"] == "skipped"

    aggregator = Company(
        project_id=UUID(project["id"]),
        company_name="instagram.com",
        website_url="https://instagram.com/sample-company",
        domain="instagram.com",
        source="url",
    )
    db.add(aggregator)
    db.commit()
    result = auth.post(f"/api/companies/{aggregator.id}/analyze", json={}).json()
    assert result["analysis_status"] == "excluded" and result["is_aggregator"]

    failing = add_url(auth, project["id"], "https://failure.example")

    def fail(url):
        raise ScrapeError("接続できません。")

    monkeypatch.setattr(web_analysis, "scrape_company", fail)
    result = auth.post(f"/api/companies/{failing['id']}/analyze", json={}).json()
    assert result["analysis_status"] == "failed"
    assert result["analysis_error"] == "接続できません。"


def test_analysis_marks_redirected_domain_duplicate(auth, monkeypatch):
    project = make_project(auth)
    original = add_url(auth, project["id"], "https://canonical.example")
    duplicate = add_url(auth, project["id"], "https://redirect.example")
    monkeypatch.setattr(
        web_analysis,
        "scrape_company",
        lambda url: (
            FetchedPage("https://canonical.example/", HTML),
            PageData(company_name="別名"),
        ),
    )
    result = auth.post(f"/api/companies/{duplicate['id']}/analyze", json={}).json()
    assert result["analysis_status"] == "duplicate"
    assert result["duplicate_of_id"] == original["id"]


def test_batch_analysis_and_access_isolation(auth, users, monkeypatch):
    project = make_project(auth)
    first = add_url(auth, project["id"], "https://first.example")
    second = add_url(auth, project["id"], "https://second.example")
    monkeypatch.setattr(
        web_analysis,
        "scrape_company",
        lambda url: (FetchedPage(url, HTML), PageData(company_name=urlsplit_name(url))),
    )
    response = auth.post(
        f"/api/projects/{project['id']}/web-analysis",
        json={"company_ids": [first["id"], second["id"]], "limit": 20},
    )
    assert response.status_code == 200
    assert {item["analysis_status"] for item in response.json()} == {"completed"}
    assert (
        auth.post(
            f"/api/projects/{project['id']}/web-analysis",
            json={"company_ids": [str(uuid4())]},
        ).status_code
        == 404
    )

    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.post(f"/api/companies/{first['id']}/analyze", json={}).status_code == 404
    assert auth.post(f"/api/projects/{project['id']}/web-analysis", json={}).status_code == 404


def urlsplit_name(url):
    return url.split("//", 1)[-1].split(".", 1)[0]
