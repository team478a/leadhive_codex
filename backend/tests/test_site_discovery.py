from sqlalchemy import select

from app.models import Company, LeadSourceObservation
from app.services import collection
from app.services.collection import Candidate
from app.services.collection_jobs import save_candidates, start_job
from app.services.site_discovery import assess_search_url, is_reference_host
from tests.test_collection import FakeClient, make_project


def test_article_routes_to_same_host_homepage_as_unconfirmed_candidate(monkeypatch):
    monkeypatch.setattr(collection.settings, "serper_api_key", "test-only")
    monkeypatch.setattr(
        collection.httpx,
        "Client",
        lambda **kwargs: FakeClient(
            [
                {
                    "organic": [
                        {
                            "title": "業界比較記事",
                            "link": "https://publisher.example/blog/vendors?ref=search",
                            "snippet": "比較記事",
                        }
                    ]
                }
            ],
            [],
        ),
    )

    [candidate] = collection.search_serper("サービス", "地域", 10)
    assert candidate.company_name == "publisher.example"
    assert candidate.website_url == "https://publisher.example"
    assert candidate.reference_url == "https://publisher.example/blog/vendors?ref=search"
    assert candidate.site_discovery["official_site_status"] == "NOT_CONFIRMED"
    assert candidate.site_discovery["contact_status"] == "NOT_CHECKED"


def test_reference_host_boundaries_and_non_article_service_pages():
    assert is_reference_host("www.hotpepper.jp")
    assert not is_reference_host("not-hotpepper.jp")
    assert not is_reference_host("hotpepper.jp.example.org")
    service = assess_search_url("https://agency.example/services/sns")
    assert service["kind"] == "BUSINESS_SITE_REVIEW"
    assert assess_search_url("https://agency.example/catalog.xlsx")["kind"] == "REFERENCE_DOCUMENT"


def test_article_hint_is_recorded_without_confirming_identity(auth, db):
    project = make_project(auth)
    hint = assess_search_url("https://publisher.example/blog/vendors")
    job = start_job(db, project["id"], "serper", "service", "nationwide")
    save_candidates(
        db,
        job,
        [
            Candidate(
                "publisher.example",
                "https://publisher.example",
                reference_url=hint["reference_url"],
                site_discovery=hint,
            )
        ],
    )
    company = db.scalar(select(Company).where(Company.project_id == project["id"]))
    observation = db.scalar(
        select(LeadSourceObservation).where(
            LeadSourceObservation.collection_job_id == job.id
        )
    )
    assert company.website_url == "https://publisher.example"
    assert company.reference_url == hint["reference_url"]
    assert company.analysis_status != "excluded"
    assert observation.facts["site_discovery"] == hint


def test_documents_are_retained_in_discovery_but_not_saved_as_companies(auth, db):
    project = make_project(auth)
    job = start_job(db, project["id"], "serper", "service", "nationwide")
    hint = assess_search_url("https://publisher.example/catalog.pdf")
    candidate = Candidate("資料", hint["reference_url"], site_discovery=hint)
    save_candidates(db, job, [candidate])
    assert job.saved_count == 0
    assert job.excluded_count == 1
    assert db.scalar(select(Company.id).where(Company.project_id == project["id"])) is None
