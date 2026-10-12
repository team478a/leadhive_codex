import pytest
from sqlalchemy import func, select

from app.models import ProjectMember, SourceDomainExclusion
from app.services.collection import Candidate
from app.services.collection_jobs import save_candidates, start_job
from app.services.scraper import FetchedPage, scrape_company
from app.services.source_exclusions import excluded
from app.services.source_page_policy import page_reason
from app.services.web_analysis import analyze
from tests.test_sendability import company_fixture


def test_summary_title_at_analysis_and_contact_wrapper():
    assert (
        page_reason("<title>おすすめの店7選</title>", "https://new.example/list") == "ARTICLE_PAGE"
    )
    assert page_reason("<title>店舗一覧｜公式サイト</title>", "https://new.example/stores") == ""
    assert (
        page_reason(
            '<title>おすすめの店7選</title><form><input name="email" type="email">'
            '<textarea name="message"></textarea></form>',
            "https://new.example/contact",
        )
        == ""
    )


def register(auth, company, url="https://www.listing.example/list"):
    return auth.post(
        f"/api/projects/{company.project_id}/source-exclusions",
        json={
            "evidence_url": url,
            "reason": "Human確認済みのまとめサイト",
            "confirmed_domain_wide": True,
        },
    )


def test_memory_is_project_local_exact_domain_reversible_and_skips_ingestion(auth, db):
    company = company_fixture(auth, db)
    response = register(auth, company)
    assert response.status_code == 201
    rule = response.json()
    assert rule["domain"] == "listing.example"
    assert register(auth, company).json()["id"] == rule["id"]
    assert db.scalar(select(func.count()).select_from(SourceDomainExclusion)) == 1
    assert excluded(db, company.project_id, "https://LISTING.example/")
    assert not excluded(db, company.project_id, "https://listing.example.evil.test/")
    assert not excluded(db, company.project_id, "https://other.listing.example/")
    job = start_job(db, company.project_id, "serper", "SNS", "北海道")
    save_candidates(
        db,
        job,
        [
            Candidate("媒体", "https://listing.example/list"),
            Candidate("事業者", "https://provider.example/"),
        ],
    )
    assert job.excluded_count == 1 and job.saved_count == 1
    other = company_fixture(auth, db)
    assert other.project_id != company.project_id
    assert not excluded(db, other.project_id, "https://listing.example/")
    path = f"/api/projects/{company.project_id}/source-exclusions"
    assert auth.post(f"{path}/{rule['id']}/deactivate").status_code == 200
    assert not excluded(db, company.project_id, "https://listing.example/")
    assert auth.get(path).json()[0]["active"] is False
    assert [item["action"] for item in auth.get(path).json()[0]["history"]] == [
        "REGISTER",
        "REGISTER",
        "DEACTIVATE",
    ]


def test_domain_wide_confirmation_is_required(auth, db):
    company = company_fixture(auth, db)
    response = auth.post(
        f"/api/projects/{company.project_id}/source-exclusions",
        json={"evidence_url": "https://listing.example/", "reason": "記事ページ"},
    )
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(SourceDomainExclusion)) == 0


def test_remembered_source_does_not_consume_target_quota(auth, db):
    from app.services.target_collection import bounded_candidates

    company = company_fixture(auth, db)
    assert register(auth, company).status_code == 201
    job = start_job(db, company.project_id, "serper", "SNS", "北海道")
    candidates = [
        Candidate("媒体", "https://listing.example/list"),
        Candidate("事業者", "https://provider.example/"),
    ]
    assert bounded_candidates(db, job, candidates, 1) == candidates
    save_candidates(db, job, candidates)
    assert job.saved_count == 1 and job.excluded_count == 1


def test_downgrade_refuses_to_lose_domain_memory(auth, db, monkeypatch):
    import importlib.util
    from pathlib import Path

    company = company_fixture(auth, db)
    assert register(auth, company).status_code == 201
    path = (
        Path(__file__).parents[1] / "migrations/versions/3a9d102e7711_source_domain_exclusions.py"
    )
    spec = importlib.util.spec_from_file_location("source_memory_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration.op, "get_bind", lambda: db.connection())
    with pytest.raises(RuntimeError, match="Source exclusions exist"):
        migration.downgrade()


def test_remembered_domain_stops_analysis_before_get(auth, db, monkeypatch):
    company = company_fixture(auth, db)
    company.website_url = "https://listing.example/"
    db.commit()
    assert register(auth, company).status_code == 201
    monkeypatch.setattr(
        "app.services.web_analysis.scrape_company",
        lambda *args, **kw: pytest.fail("GET must not happen"),
    )
    assert analyze(db, company).analysis_status == "excluded"
    assert "SOURCE_DOMAIN_EXCLUDED" in company.analysis_error


def test_human_boundary_viewer_and_cross_project(auth, db, users):
    company = company_fixture(auth, db)
    path = f"/api/projects/{company.project_id}/source-exclusions"
    assert register(auth, company).status_code == 201
    assert (
        auth.post(
            path,
            headers={"Authorization": "Bearer fake-agent"},
            json={"evidence_url": "https://listing.example/", "reason": "x"},
        ).status_code
        == 403
    )
    auth.post("/api/auth/logout")
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(path).status_code == 200
    assert register(auth, company).status_code == 404


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/", "javascript:alert(1)", "https://secret:password@listing.example/"]
)
def test_bad_source_urls_rejected(auth, db, url):
    company = company_fixture(auth, db)
    assert register(auth, company, url).status_code == 422


def test_article_requires_page_evidence_and_never_learns_domain():
    html = "<title>SNS運用代行会社おすすめ</title>"
    assert page_reason(html, "https://agency.example/") == ""
    assert (
        page_reason(
            html + '<meta property="og:type" content="article">', "https://agency.example/post"
        )
        == "ARTICLE_PAGE"
    )


def test_contact_form_article_wrapper_is_not_a_comparison_page():
    html = (
        "<title>SNS運用代行会社おすすめ</title><article>"
        '<form><textarea name="message"></textarea></form></article>'
    )
    assert page_reason(html, "https://agency.example/contact") == ""
    assert (
        page_reason(
            "<title>SNS運用代行｜当社おすすめプラン</title><article>事業内容</article>",
            "https://agency.example/",
        )
        == ""
    )


def test_article_recovers_business_root_and_finds_contact(monkeypatch):
    visited = []
    pages = {
        "https://agency.example/blog/post": (
            "<title>SNS運用代行会社おすすめ</title><article>比較記事</article>"
        ),
        "https://agency.example/": (
            '<title>株式会社テスト</title><a href="/contact">お問い合わせ</a>'
        ),
        "https://agency.example/contact": (
            '<form><input name="email"><textarea name="message"></textarea></form>'
        ),
    }

    def fetch(self, url):
        visited.append(url)
        return FetchedPage(url, pages[url])

    monkeypatch.setattr("app.services.scraper.SafeFetcher.fetch_html", fetch)
    page, data = scrape_company("https://agency.example/blog/post")
    assert page.url == "https://agency.example/"
    assert data.contact_url == "https://agency.example/contact"
    assert data.source_exclusion_reason == ""
    assert len(visited) <= 5


def test_article_root_stops_before_publisher_contact_and_unknown_is_preserved(monkeypatch):
    visited = []

    def fetch(self, url):
        visited.append(url)
        return FetchedPage(
            url,
            "<title>SNS運用代行会社おすすめ</title>"
            '<article><a href="/contact">お問い合わせ</a></article>',
        )

    monkeypatch.setattr("app.services.scraper.SafeFetcher.fetch_html", fetch)
    _, data = scrape_company("https://publisher.example/")
    assert data.source_exclusion_reason == "ARTICLE_PAGE"
    assert data.contact_url == "" and len(visited) == 1


def test_contact_redirect_to_publisher_is_not_retained(monkeypatch):
    def fetch(self, url):
        if url.endswith("/contact"):
            return FetchedPage("https://www.dreamnews.jp/press/1/", "<title>ニュース</title>")
        return FetchedPage(url, '<title>会社概要</title><a href="/contact">お問い合わせ</a>')

    monkeypatch.setattr("app.services.scraper.SafeFetcher.fetch_html", fetch)
    _, data = scrape_company("https://agency.example/")
    assert data.contact_url == ""
    assert "contact_url" not in data.field_evidence
    assert data.crawl_errors[0]["reason"] == "NON_COMPANY_PAGE"
