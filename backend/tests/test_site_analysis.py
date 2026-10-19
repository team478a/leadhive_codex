from uuid import UUID

from app.models import ApplicationSettings, Company, OperationJob, Project
from app.services import web_analysis
from app.services.collection import Candidate
from app.services.collection_jobs import save_candidates, start_job
from app.services.scraper import FetchedPage, PageFetchCache
from app.services.site_analysis import (
    analyze_site_company,
    auto_site_analysis_enabled,
    enqueue_site_analysis,
)
from tests.test_collection import make_project


def test_collection_automatically_queues_site_analysis_and_setting_can_disable(auth, db):
    project = make_project(auth)
    project_id = UUID(project["id"])
    project_record = db.get(Project, project_id)
    collection = start_job(db, project_id, "url", "", "")
    save_candidates(
        db,
        collection,
        [Candidate("自動解析対象", "https://auto-analysis.example")],
    )
    assert project_record is not None
    assert project_record.id == project_id
    job = db.query(OperationJob).filter_by(operation_type="site_analysis").one()
    assert job.payload["company_ids"]

    setting = ApplicationSettings(id=1, auto_site_analysis=False)
    db.add(setting)
    db.commit()
    assert not auto_site_analysis_enabled(db)
    disabled_collection = start_job(db, project_id, "url", "", "")
    save_candidates(
        db,
        disabled_collection,
        [Candidate("自動解析停止", "https://auto-analysis-disabled.example")],
    )
    assert db.query(OperationJob).filter_by(operation_type="site_analysis").count() == 1


def test_obvious_public_domains_and_article_titles_are_filtered_before_save(auth, db):
    project = make_project(auth)
    collection = start_job(db, UUID(project["id"]), "serper", "問い合わせ", "全国")
    save_candidates(
        db,
        collection,
        [
            Candidate("横浜市", "https://city.yokohama.lg.jp/contact"),
            Candidate("2025年版 工務店を調べてみた", "https://article.example.jp/column"),
            Candidate("株式会社サンプル", "https://sample.example.jp"),
        ],
    )

    saved = db.query(Company).filter_by(project_id=UUID(project["id"])).all()
    assert [company.company_name for company in saved] == ["株式会社サンプル"]
    assert collection.excluded_count == 2


def test_site_analysis_queue_commits_and_expunge_all_per_200_company_chunk(auth, db, monkeypatch):
    project = make_project(auth)
    project_id = UUID(project["id"])
    companies = [
        Company(
            project_id=project_id,
            company_name=f"会社{index}",
            domain=f"company-{index}.example",
            website_url=f"https://company-{index}.example",
            source="url",
        )
        for index in range(2500)
    ]
    db.add_all(companies)
    db.commit()
    company_ids = [company.id for company in companies]
    db.expunge_all()

    commit_count = 0
    expunge_count = 0
    original_commit = db.commit
    original_expunge_all = db.expunge_all

    def counted_commit():
        nonlocal commit_count
        commit_count += 1
        original_commit()

    def counted_expunge_all():
        nonlocal expunge_count
        expunge_count += 1
        original_expunge_all()

    monkeypatch.setattr(db, "commit", counted_commit)
    monkeypatch.setattr(db, "expunge_all", counted_expunge_all)
    job = enqueue_site_analysis(db, project_id, company_ids)

    assert job is not None
    assert job.total_count == 2500
    assert len(job.payload["company_ids"]) == 2500
    assert commit_count == 13
    assert expunge_count == 13


def test_manual_site_analysis_still_queues_when_automatic_setting_is_off(auth, db):
    project = make_project(auth)
    project_id = UUID(project["id"])
    company = Company(
        project_id=project_id,
        company_name="手動解析対象",
        domain="manual-analysis.example",
        website_url="https://manual-analysis.example",
        source="url",
    )
    db.add_all([company, ApplicationSettings(id=1, auto_site_analysis=False)])
    db.commit()

    job = enqueue_site_analysis(db, project_id, [company.id])

    assert job is not None
    assert job.payload["company_ids"] == [str(company.id)]


def test_site_analysis_shares_one_page_cache_between_web_and_form_analysis(auth, db, monkeypatch):
    from app.services import form_intelligence

    project = make_project(auth)
    project_id = UUID(project["id"])
    company = Company(
        project_id=project_id,
        company_name="解析キャッシュ",
        domain="shared-cache.example",
        website_url="https://shared-cache.example",
        source="url",
    )
    db.add(company)
    db.commit()
    received_caches = []

    def web_analyze(_db, item, _force=False, *, page_cache=None):
        item.analysis_status = "completed"
        received_caches.append(page_cache)
        return item

    def form_analyze(_db, _item, _force=False, *, page_cache=None):
        received_caches.append(page_cache)
        return []

    monkeypatch.setattr(web_analysis, "analyze", web_analyze)
    monkeypatch.setattr(form_intelligence, "analyze_company_forms", form_analyze)

    assert analyze_site_company(db, company)
    assert len(received_caches) == 2
    assert received_caches[0] is received_caches[1]


def test_page_fetch_cache_reuses_the_same_synthetic_page():
    class Fetcher:
        calls = 0

        def fetch_html(self, url):
            self.calls += 1
            return FetchedPage(url, "<main>synthetic fixture</main>")

    cache = PageFetchCache()
    fetcher = Fetcher()
    first = cache.fetch(fetcher, "https://fixture.example")
    second = cache.fetch(fetcher, "https://fixture.example/")

    assert first is second
    assert fetcher.calls == 1
