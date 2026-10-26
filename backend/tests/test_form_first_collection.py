import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import (
    CollectionDiscoveryHit,
    Company,
    FormProfile,
    LeadSourceObservation,
    OperationJob,
)
from app.schema_workflow import OperationJobInput
from app.services import form_first_collection as form_first
from app.services.collection import Candidate
from app.services.collection_jobs import save_candidates, start_job
from app.services.collection_query_plan import plan_hash, plan_snapshot, planned_queries
from app.services.contact_discovery import contact_pages
from app.services.scraper import FetchedPage, ScrapeError
from tests.test_collection import make_project


def test_known_analyzed_company_is_skipped_before_fetch(auth, db, monkeypatch):
    project = make_project(auth)
    project_id = UUID(project["id"])
    company = Company(
        project_id=project_id,
        company_name="株式会社既存",
        website_url="https://known.test/",
        domain="known.test",
        source="form_first",
        contact_url="https://known.test/contact",
        form_first_contact_url="https://known.test/contact",
    )
    db.add(company)
    db.flush()
    db.add(
        FormProfile(
            company_id=company.id,
            form_url=company.contact_url,
            form_status="READY",
            last_analyzed_at=datetime.now(timezone.utc),
        )
    )
    collection = start_job(db, project_id, "serper", "お問い合わせ", "東京都")
    hit = CollectionDiscoveryHit(
        collection_job_id=collection.id,
        position=1,
        snapshot={"link": company.contact_url, "title": "お問い合わせ"},
        raw_hash="f" * 64,
        classification="OFFICIAL_SITE_CANDIDATE",
        classification_reason="OFFICIAL_IDENTITY_NOT_VERIFIED",
        disposition="CAPTURED",
        retain_until=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(hit)
    db.commit()
    monkeypatch.setattr(
        form_first,
        "_fetch_candidate",
        lambda _url: pytest.fail("analyzed known company must not be fetched"),
    )

    accepted = form_first.process_search_results(
        db,
        collection,
        [Candidate("お問い合わせ", company.contact_url, discovery_hit_id=hit.id)],
        {},
        lambda: False,
    )

    assert accepted == []
    db.refresh(hit)
    assert hit.classification_reason == "REJECT_ALREADY_KNOWN"
    assert hit.disposition == "DUPLICATE"
    assert collection._form_first_metrics["counts"]["skipped_known_before_fetch"] == 1


def test_candidate_fetch_concurrency_serializes_hosts_and_honors_stop(monkeypatch):
    monkeypatch.setattr(settings, "form_first_fetch_concurrency", 2)
    lock = Lock()
    active_by_host: dict[str, int] = {}
    max_by_host: dict[str, int] = {}
    global_active = 0
    max_global = 0

    def fetch(url):
        nonlocal global_active, max_global
        host = url.split("/")[2]
        with lock:
            active_by_host[host] = active_by_host.get(host, 0) + 1
            max_by_host[host] = max(max_by_host.get(host, 0), active_by_host[host])
            global_active += 1
            max_global = max(max_global, global_active)
        time.sleep(0.02)
        with lock:
            active_by_host[host] -= 1
            global_active -= 1
        return "FORM_FOUND", []

    monkeypatch.setattr(form_first, "_fetch_candidate", fetch)
    items = [
        (0, "https://a.test/1", "a.test"),
        (1, "https://a.test/2", "a.test"),
        (2, "https://b.test/1", "b.test"),
        (3, "https://b.test/2", "b.test"),
    ]
    result = form_first._fetch_candidates_by_host(items, lambda: False)
    assert list(result) == [0, 2, 1, 3]
    assert max_global == 2
    assert max_by_host == {"a.test": 1, "b.test": 1}

    checks = 0

    def stopped():
        nonlocal checks
        checks += 1
        return checks > 1

    stopped_result = form_first._fetch_candidates_by_host(items, stopped)
    assert set(stopped_result) == {0, 2}


def test_site_analysis_is_deferred_by_default(auth, db, monkeypatch):
    project = make_project(auth)
    project_id = UUID(project["id"])
    company = Company(
        project_id=project_id,
        company_name="株式会社Deferred",
        website_url="https://deferred.test/",
        domain="deferred.test",
        source="form_first",
        contact_url="https://deferred.test/contact",
        form_first_contact_url="https://deferred.test/contact",
    )
    db.add(company)
    collection = start_job(db, project_id, "serper", "お問い合わせ", "東京都")
    db.commit()
    monkeypatch.setattr(settings, "form_first_inline_site_analysis", False)
    form_first.queue_saved_company_analysis(
        db,
        collection,
        [
            Candidate(
                company_name=company.company_name,
                website_url=company.website_url,
                contact_url=company.contact_url,
                form_first_contact_url=company.form_first_contact_url,
                collection_method="form_first",
                site_discovery={"form_first_form_status": "FORM_FOUND"},
            )
        ],
    )
    queued = db.scalar(select(OperationJob).where(OperationJob.operation_type == "site_analysis"))
    assert queued is not None
    assert str(company.id) in queued.payload["company_ids"]


def test_form_first_queries_are_versioned_and_keep_the_query_modifiers():
    queries = form_first.build_form_first_queries(["工務店"], list(form_first.QUERY_TYPES))
    assert [item["query_type"] for item in queries] == list(form_first.QUERY_TYPES)
    assert queries[0]["query"] == (
        "intitle:お問い合わせ 工務店 -求人 -採用 -ポータル -ランキング -まとめ"
    )
    assert queries[1]["query"].startswith("inurl:contact 工務店")
    assert queries[2]["query"].startswith("inurl:inquiry 工務店")
    assert queries[3]["query"].startswith('"お問い合わせフォーム" 工務店')
    assert len(form_first.build_form_first_queries(["工務店", "工務店"], ["form_words"])) == 1
    with pytest.raises(ValueError):
        form_first.build_form_first_queries(["工務店"], ["unknown"])


def test_restaurant_queries_add_industry_exclusions_without_changing_general_queries():
    general = form_first.build_form_first_queries(["カフェ"], ["form_words"])[0]["query"]
    restaurant = form_first.build_form_first_queries(
        ["カフェ"], ["form_words"], industry="restaurant"
    )[0]["query"]
    assert general == '"お問い合わせフォーム" カフェ -求人 -採用 -ポータル -ランキング -まとめ'
    assert restaurant == (
        '"お問い合わせフォーム" カフェ -求人 -採用 -ポータル -ランキング -まとめ '
        "-食べログ -ぐるなび -ホットペッパー -Retty -一休 -予約"
    )
    assert form_first.RESTAURANT_KEYWORDS == (
        "居酒屋",
        "レストラン",
        "カフェ",
        "焼肉",
        "ラーメン",
        "寿司",
        "和食",
        "イタリアン",
    )
    planned = form_first.build_form_first_queries(
        list(form_first.RESTAURANT_KEYWORDS),
        list(form_first.QUERY_TYPES),
        industry="restaurant",
    )
    first_twenty = planned[:20]
    counts = {
        keyword: sum(item["industry_keyword"] == keyword for item in first_twenty)
        for keyword in form_first.RESTAURANT_KEYWORDS
    }
    assert all(count in {2, 3} for count in counts.values())


def test_company_first_plan_hash_is_unchanged_by_optional_form_first_fields():
    payload = {
        "keywords": ["工務店"],
        "region": "全国",
        "target_count": 100,
        "presence_search": None,
    }
    old_snapshot = plan_snapshot(payload)
    company_first_snapshot = plan_snapshot(
        {
            **payload,
            "collection_method": "company_first",
            "form_first_query_types": list(form_first.QUERY_TYPES),
        }
    )
    assert old_snapshot == company_first_snapshot
    assert plan_hash(old_snapshot) == plan_hash(company_first_snapshot)


def test_form_first_plan_hash_binds_corporate_number_requirement():
    payload = {
        "keywords": ["intitle:お問い合わせ 工務店"],
        "region": "神奈川県",
        "target_count": 10000,
        "collection_method": "form_first",
        "form_first_query_types": ["intitle_contact"],
        "form_first_industry_keywords": ["工務店"],
    }
    optional = plan_snapshot(payload)
    required = plan_snapshot({**payload, "require_corporate_number": True})
    assert optional["require_corporate_number"] is False
    assert required["require_corporate_number"] is True
    assert plan_hash(optional) != plan_hash(required)


def test_form_first_plan_hash_binds_restaurant_query_policy_but_omits_general_default():
    payload = {
        "keywords": ['"お問い合わせフォーム" カフェ -求人 -採用 -ポータル -ランキング -まとめ'],
        "region": "名古屋市",
        "target_count": 10000,
        "collection_method": "form_first",
        "form_first_query_types": ["form_words"],
        "form_first_industry_keywords": ["カフェ"],
    }
    general = plan_snapshot(payload)
    restaurant = plan_snapshot(
        {
            **payload,
            "form_first_industry": "restaurant",
            "form_first_query_order_version": "round-robin-v2",
        }
    )
    assert "form_first_industry" not in general
    assert restaurant["form_first_industry"] == "restaurant"
    assert restaurant["form_first_query_order_version"] == "round-robin-v2"
    assert plan_hash(general) != plan_hash(restaurant)


def test_form_first_payload_defaults_to_twenty_request_budget_and_supports_prefecture_order():
    payload = OperationJobInput(
        operation_type="collect_search",
        source="serper",
        keywords=["工務店"],
        region="全国",
        region_mode="prefecture_order",
        collection_method="form_first",
    )
    assert payload.target_count == 10000
    snapshot = plan_snapshot(
        {
            **payload.model_dump(mode="json"),
            "keywords": ["intitle:お問い合わせ 工務店"],
            "segment_request_limit": 20,
            "collection_method": "form_first",
        }
    )
    queries = planned_queries(snapshot)
    assert len(queries) == 47
    assert queries[0] == ("intitle:お問い合わせ 工務店", "北海道")
    assert snapshot["request_budget"] == 20


def test_form_first_collection_rejects_unsupported_execution_options():
    with pytest.raises(ValueError):
        OperationJobInput(
            operation_type="collect_search",
            source="serper",
            keywords=["工務店"],
            region="東京都",
            collection_method="form_first",
            auto_continue=True,
        )
    with pytest.raises(ValueError):
        OperationJobInput(
            operation_type="collect_search",
            source="serper",
            keywords=["工務店"],
            region="東京都",
            require_corporate_number=True,
        )
    with pytest.raises(ValueError):
        OperationJobInput(
            operation_type="collect_search",
            source="serper",
            keywords=["工務店"],
            region="東京都",
            collection_method="form_first",
            form_first_query_types=["intitle_contact", "intitle_contact"],
        )
    with pytest.raises(ValueError):
        OperationJobInput(
            operation_type="collect_search",
            source="serper",
            keywords=["工務店"],
            region="東京都",
            collection_method="form_first",
            condition_request_id=UUID(int=1),
        )
    assert (
        OperationJobInput(
            operation_type="collect_search",
            source="serper",
            keywords=["カフェ"],
            region="名古屋市",
            collection_method="form_first",
            form_first_industry="restaurant",
        ).form_first_industry
        == "restaurant"
    )
    with pytest.raises(ValueError):
        OperationJobInput(
            operation_type="collect_search",
            source="serper",
            keywords=["カフェ"],
            region="名古屋市",
            form_first_industry="restaurant",
        )


def test_search_result_classification_uses_contact_and_exclusion_rules(auth, db):
    project = make_project(auth)
    project_id = UUID(project["id"])
    assert (
        form_first.classify_search_result(
            db, project_id, Candidate("お問い合わせ", "https://sample.test/contact")
        )
        == "CONTACT_PAGE_CANDIDATE"
    )
    assert (
        form_first.classify_search_result(
            db, project_id, Candidate("お問い合わせ", "https://city.yokohama.lg.jp/contact")
        )
        == "REJECT_PUBLIC_SECTOR"
    )
    assert (
        form_first.classify_search_result(
            db, project_id, Candidate("お問い合わせ", "https://docs.google.com/forms/d/abc")
        )
        == "REJECT_EXTERNAL_FORM_SERVICE"
    )
    assert (
        form_first.classify_search_result(
            db, project_id, Candidate("会社概要", "https://sample.test/about")
        )
        == "REJECT_NOT_CONTACT"
    )
    assert (
        form_first.classify_search_result(
            db, project_id, Candidate("お問い合わせ", "https://beauty.hotpepper.jp/contact")
        )
        == "REJECT_REFERENCE_HOST"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://city.example.lg.jp/contact",
        "https://agency.example.go.jp/contact",
        "https://school.example.ed.jp/contact",
        "https://university.example.ac.jp/contact",
        "https://pref.example/contact",
        "https://town.example/contact",
        "https://vill.example/contact",
    ],
)
def test_public_sector_domains_are_rejected(auth, db, url):
    project = make_project(auth)
    assert (
        form_first.classify_search_result(db, UUID(project["id"]), Candidate("お問い合わせ", url))
        == "REJECT_PUBLIC_SECTOR"
    )


def test_excluded_domain_and_non_contact_search_results_are_rejected(auth, db, monkeypatch):
    project = make_project(auth)
    project_id = UUID(project["id"])
    monkeypatch.setattr(
        form_first, "excluded", lambda _db, _project_id, url: "blocked.example" in url
    )
    assert (
        form_first.classify_search_result(
            db, project_id, Candidate("お問い合わせ", "https://blocked.example/contact")
        )
        == "REJECT_EXCLUDED_DOMAIN"
    )
    assert (
        form_first.classify_search_result(
            db, project_id, Candidate("会社概要", "https://sample.test/about")
        )
        == "REJECT_NOT_CONTACT"
    )


def test_extract_company_facts_supports_tables_dl_jsonld_trade_and_title():
    table = """<table><tr><th>会社名</th><td>株式会社表</td></tr>
      <tr><th>所在地</th><td>東京都千代田区丸の内1-1</td></tr>
      <tr><th>TEL</th><td>03-1234-5678</td></tr>
      <tr><th>事業内容</th><td>建築工事と設計</td></tr></table>"""
    dl = "<dl><dt>商号</dt><dd>株式会社DL</dd><dt>住所</dt><dd>東京都千代田区1-1</dd></dl>"
    jsonld = (
        '<script type="application/ld+json">'
        '{"@type":"Organization","name":"株式会社JSON",'
        '"telephone":"03-2222-3333","address":{"addressRegion":"東京都",'
        '"addressLocality":"港区","streetAddress":"1-2"}}</script>'
    )
    trade = "<table><tr><th>販売業者</th><td>株式会社販売</td></tr></table>"
    title = "<title>株式会社タイトル｜公式サイト</title>"

    facts = form_first.extract_company_facts(
        [
            ("root", "https://example.test/", jsonld),
            ("trade", "https://example.test/legal", trade),
            ("about", "https://example.test/company", table),
        ]
    )
    assert facts["company_name"]["value"] == "株式会社表"
    assert facts["company_name"]["method"] == "COMPANY_TABLE"
    assert facts["address"]["value"] == "東京都千代田区丸の内1-1"
    assert facts["phone"]["value"] == "03-1234-5678"
    assert facts["business_summary"]["value"] == "建築工事と設計"
    dl_facts = form_first.extract_company_facts([("about", "https://example.test/", dl)])
    assert dl_facts["company_name"]["value"] == "株式会社DL"
    json_facts = form_first.extract_company_facts([("root", "https://example.test/", jsonld)])
    assert json_facts["company_name"]["method"] == "JSON_LD_ORGANIZATION"
    assert json_facts["address"]["method"] == "JSON_LD_ADDRESS"
    trade_facts = form_first.extract_company_facts([("trade", "https://example.test/", trade)])
    assert trade_facts["company_name"]["method"] == "TRADE_TABLE"
    title_facts = form_first.extract_company_facts([("root", "https://example.test/", title)])
    assert title_facts["company_name"]["value"] == "株式会社タイトル"
    plain_text_facts = form_first.extract_company_facts(
        [("root", "https://example.test/", "事業内容らしき文章をページ本文に記載")]
    )
    assert "business_summary" not in plain_text_facts


def test_gbizinfo_lookup_matches_unique_location_and_handles_other_outcomes(monkeypatch):
    class Response:
        status_code = 200

        def __init__(self, items):
            self.items = items

        def raise_for_status(self):
            return None

        def json(self):
            return {"hojin-infos": self.items}

    class Client:
        items = []

        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return Response(self.items)

    monkeypatch.setattr(form_first.httpx, "Client", Client)
    monkeypatch.setattr(settings, "gbizinfo_api_token", "synthetic-token")
    Client.items = [
        {
            "name": "株式会社テスト",
            "location": "東京都千代田区丸の内1-1",
            "corporateNumber": "1234567890123",
        },
        {"name": "別会社", "location": "大阪府大阪市", "corporateNumber": "0000000000000"},
    ]
    assert form_first.lookup_corporate_number("株式会社テスト", "東京都千代田区丸の内1-1") == {
        "status": "CORPORATE_NUMBER_MATCHED",
        "corporate_number": "1234567890123",
    }
    Client.items.append(
        {
            "name": "株式会社テスト支店",
            "location": "東京都千代田区丸の内1-1",
            "corporateNumber": "1111111111111",
        }
    )
    ambiguous = form_first.lookup_corporate_number("株式会社テスト", "東京都千代田区丸の内1-1")
    assert ambiguous["status"] == "CORPORATE_NUMBER_AMBIGUOUS"
    Client.items = []
    not_found = form_first.lookup_corporate_number("株式会社テスト", "東京都千代田区")
    assert not_found["status"] == "CORPORATE_NUMBER_NOT_FOUND"
    monkeypatch.setattr(settings, "gbizinfo_api_token", "")
    skipped = form_first.lookup_corporate_number("株式会社テスト", "東京都")
    assert skipped["status"] == "CORPORATE_CHECK_SKIPPED"


def test_contact_page_and_company_pages_are_get_only_and_capped_at_four(monkeypatch):
    contact_url = "https://fixture.test/contact"
    pages = {
        contact_url: (
            '<form><input type="email" name="email"><textarea name="message"></textarea></form>'
        ),
        "https://fixture.test/": '<a href="/company">会社概要</a><a href="/legal">特定商取引法</a>',
        "https://fixture.test/company": (
            "<table><tr><th>会社名</th><td>株式会社Fixture</td></tr></table>"
        ),
        "https://fixture.test/legal": (
            "<table><tr><th>販売業者</th><td>株式会社Fixture</td></tr></table>"
        ),
    }

    class Fetcher:
        requested = []

        def __init__(self):
            self.site_root = ""

        def fetch_html(self, url):
            self.requested.append(url)
            if url not in pages:
                raise AssertionError(f"Unexpected URL: {url}")
            return FetchedPage(url, pages[url])

        def close(self):
            return None

    monkeypatch.setattr(form_first, "SafeFetcher", Fetcher)
    monkeypatch.setattr(form_first, "_minimum_host_interval", lambda _host: None)
    reason, fetched = form_first._fetch_candidate(contact_url)
    assert reason == "FORM_FOUND"
    assert len(Fetcher.requested) == 4
    assert all(url.startswith("https://fixture.test/") for url in Fetcher.requested)
    assert form_first.extract_company_facts(fetched)["company_name"]["value"] == "株式会社Fixture"


def test_reservation_form_is_detected_but_a_separate_inquiry_form_is_preferred():
    reservation = """
    <html><head><title>店舗予約</title></head><body><h1>ご予約</h1>
    <form><label>来店日<input type="date" name="visit_date"></label>
    <label>人数<input name="party_size"></label><input type="email" name="email">
    <button type="submit">予約する</button></form></body></html>
    """
    mixed = """
    <html><head><title>店舗お問い合わせ</title></head><body>
    <h2>ご予約</h2><form><label>来店日<input type="date" name="visit_date"></label>
    <label>人数<input name="party_size"></label><input type="email" name="email">
    <button type="submit">予約する</button></form>
    <h2>お問い合わせ</h2><form><textarea name="message"></textarea>
    <button type="submit">送信</button></form></body></html>
    """
    from app.services.form_reservation import reservation_form_indices

    assert form_first._contact_page_status(reservation) == "RESERVATION_FORM"
    assert reservation_form_indices(reservation, contact_context=True) == {0}
    assert form_first._contact_page_status(mixed) == "FORM_FOUND"
    assert reservation_form_indices(mixed, contact_context=True) == {0}


def test_reservation_candidate_uses_same_site_inquiry_page_when_available(monkeypatch):
    initial_url = "https://booking-fixture.test/contact"
    inquiry_url = "https://booking-fixture.test/inquiry"
    pages = {
        initial_url: """
        <html><head><title>店舗予約</title></head><body><h1>ご予約</h1>
        <form><label>来店日<input type="date" name="visit_date"></label>
        <label>人数<input name="party_size"></label><input type="email" name="email">
        <button type="submit">予約する</button></form></body></html>
        """,
        "https://booking-fixture.test/": '<a href="/inquiry">お問い合わせ</a>',
        inquiry_url: '<form><textarea name="message"></textarea><button>送信</button></form>',
    }

    class Fetcher:
        requested = []

        def __init__(self):
            self.site_root = ""

        def fetch_html(self, url):
            self.requested.append(url)
            return FetchedPage(url, pages[url])

        def close(self):
            return None

    monkeypatch.setattr(form_first, "SafeFetcher", Fetcher)
    monkeypatch.setattr(form_first, "_minimum_host_interval", lambda _host: None)
    reason, fetched = form_first._fetch_candidate(initial_url)

    assert reason == "FORM_FOUND"
    assert Fetcher.requested == [initial_url, "https://booking-fixture.test/", inquiry_url]
    assert any(kind == "contact" and url == inquiry_url for kind, url, _ in fetched)
    assert len(Fetcher.requested) <= 4


def test_reservation_crawl_counts_redirected_get_attempts_toward_four_page_limit(monkeypatch):
    contact_url = "https://redirect-fixture.test/contact"
    root_url = "https://redirect-fixture.test/"
    reservation_html = """
    <html><head><title>店舗予約</title></head><body><h1>ご予約</h1>
    <form><label>来店日<input type="date" name="visit_date"></label>
    <label>人数<input name="party_size"></label>
    <button type="submit">予約する</button></form></body></html>
    """
    root_html = """<a href="/inquiry1">お問い合わせ1</a>
    <a href="/inquiry2">お問い合わせ2</a>
    <a href="/company">会社概要</a><a href="/trade">特定商取引法</a>"""

    class Fetcher:
        requested = []

        def __init__(self):
            self.site_root = ""

        def fetch_html(self, url):
            self.requested.append(url)
            if url == contact_url:
                return FetchedPage(contact_url, reservation_html)
            if url == root_url:
                return FetchedPage(root_url, root_html)
            return FetchedPage(root_url, "<p>no form</p>")

        def close(self):
            return None

    monkeypatch.setattr(form_first, "SafeFetcher", Fetcher)
    monkeypatch.setattr(form_first, "_minimum_host_interval", lambda _host: None)

    form_first._fetch_candidate(contact_url)

    assert len(Fetcher.requested) <= 4


def test_form_first_contact_page_is_the_first_analysis_candidate():
    root = "https://priority.test/"
    saved = "https://priority.test/contact"
    pages = contact_pages(
        root,
        {root: "<form><textarea name='message'></textarea></form>"},
        saved,
        prioritize_saved_contact=True,
    )
    assert next(pages) == (saved, True)


@pytest.mark.parametrize("status", ["queued", "running"])
def test_form_first_companies_join_active_site_analysis_job(auth, db, status):
    project = make_project(auth)
    active = OperationJob(
        project_id=UUID(project["id"]),
        operation_type="site_analysis",
        status=status,
        payload={"company_ids": [], "force": False},
    )
    db.add(active)
    db.commit()
    company_id = UUID(int=17)

    form_first._queue_form_analysis(db, active.project_id, [company_id])

    db.refresh(active)
    assert active.payload["company_ids"] == [str(company_id)]


def test_existing_company_reuses_form_first_pages_for_site_analysis(auth, db, monkeypatch):
    monkeypatch.setattr(settings, "form_first_inline_site_analysis", True)
    project = make_project(auth)
    project_id = UUID(project["id"])
    company = Company(
        project_id=project_id,
        company_name="株式会社既存",
        website_url="https://fixture.test/",
        domain="fixture.test",
        source="url",
    )
    db.add(company)
    db.commit()
    collection = start_job(db, project_id, "serper", "お問い合わせ", "東京都")
    hit = CollectionDiscoveryHit(
        collection_job_id=collection.id,
        position=1,
        snapshot={"link": "https://fixture.test/contact", "title": "お問い合わせ"},
        raw_hash="a" * 64,
        classification="OFFICIAL_SITE_CANDIDATE",
        classification_reason="OFFICIAL_IDENTITY_NOT_VERIFIED",
        disposition="CAPTURED",
        retain_until=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(hit)
    db.commit()
    fake_pages = {
        "https://fixture.test/contact": (
            '<form><input type="email" name="email"><textarea name="message"></textarea></form>'
        ),
        "https://fixture.test/": "<p>会社です</p>",
    }

    class Fetcher:
        def __init__(self):
            pass

        def fetch_html(self, url):
            if url not in fake_pages:
                raise ScrapeError("ページなし")
            return FetchedPage(url, fake_pages[url])

        def close(self):
            return None

    monkeypatch.setattr(form_first, "SafeFetcher", Fetcher)
    monkeypatch.setattr(form_first, "_minimum_host_interval", lambda _host: None)
    monkeypatch.setattr(settings, "gbizinfo_api_token", "")
    candidate = Candidate(
        "お問い合わせ",
        "https://fixture.test/contact",
        discovery_hit_id=hit.id,
    )
    accepted = form_first.process_search_results(
        db,
        collection,
        [candidate],
        {
            "form_first_query_map": {
                "お問い合わせ": {
                    "query_type": "intitle_contact",
                    "industry_keyword": "工務店",
                }
            }
        },
        lambda: False,
    )
    assert accepted == []
    db.refresh(company)
    assert company.contact_url == "https://fixture.test/contact"

    def analyze(_db, selected_company, *, page_cache, **_kwargs):
        class NoFetch:
            def fetch_html(self, _url):
                raise AssertionError("form-first page should be reused")

        page = page_cache.fetch(NoFetch(), "https://fixture.test/contact")
        assert "<form>" in page.html
        selected_company.analysis_status = "completed"
        return True

    monkeypatch.setattr("app.services.site_analysis.analyze_site_company", analyze)
    form_first.queue_saved_company_analysis(db, collection, accepted)
    assert not db.scalar(select(OperationJob).where(OperationJob.operation_type == "site_analysis"))
    db.refresh(hit)
    assert hit.classification_reason == "REJECT_ALREADY_KNOWN"
    assert hit.disposition == "DUPLICATE"
    assert hit.form_first_metadata["form_first_candidate"] is True
    assert hit.form_first_metadata["form_first_existing_url_added"] is True
    assert hit.form_first_metadata["form_first_form_status"] == "FORM_FOUND"
    assert "form_first_candidate" not in hit.snapshot


def test_new_form_first_company_uses_existing_candidate_ingestion(auth, db, monkeypatch):
    monkeypatch.setattr(settings, "form_first_inline_site_analysis", True)
    project = make_project(auth)
    project_id = UUID(project["id"])
    collection = start_job(db, project_id, "serper", "intitle:お問い合わせ", "東京都")
    hit = CollectionDiscoveryHit(
        collection_job_id=collection.id,
        position=1,
        snapshot={"link": "https://newfixture.test/contact", "title": "お問い合わせ"},
        raw_hash="b" * 64,
        classification="OFFICIAL_SITE_CANDIDATE",
        classification_reason="OFFICIAL_IDENTITY_NOT_VERIFIED",
        disposition="CAPTURED",
        retain_until=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(hit)
    db.commit()
    fake_pages = {
        "https://newfixture.test/contact": (
            '<form><input type="email" name="email"><textarea name="message"></textarea></form>'
        ),
        "https://newfixture.test/": '<a href="/company">会社概要</a>',
        "https://newfixture.test/company": (
            "<table><tr><th>会社名</th><td>株式会社Fixture</td></tr>"
            "<tr><th>所在地</th><td>東京都千代田区丸の内1-1</td></tr></table>"
        ),
    }

    class Fetcher:
        def fetch_html(self, url):
            return FetchedPage(url, fake_pages[url])

        def close(self):
            return None

    monkeypatch.setattr(form_first, "SafeFetcher", Fetcher)
    monkeypatch.setattr(form_first, "_minimum_host_interval", lambda _host: None)
    monkeypatch.setattr(settings, "gbizinfo_api_token", "")
    candidate = Candidate(
        "お問い合わせ", "https://newfixture.test/contact", discovery_hit_id=hit.id
    )
    accepted = form_first.process_search_results(
        db,
        collection,
        [candidate],
        {
            "form_first_query_map": {
                "intitle:お問い合わせ": {
                    "query_type": "intitle_contact",
                    "industry_keyword": "工務店",
                }
            }
        },
        lambda: False,
    )
    assert len(accepted) == 1
    save_candidates(db, collection, accepted, "intitle:お問い合わせ")

    reused = []

    def analyze(_db, selected_company, *, page_cache, **_kwargs):
        class NoFetch:
            def fetch_html(self, _url):
                raise AssertionError("form-first page should be reused")

        page = page_cache.fetch(NoFetch(), "https://newfixture.test/contact")
        reused.append(page.html)
        selected_company.analysis_status = "completed"
        return True

    monkeypatch.setattr("app.services.site_analysis.analyze_site_company", analyze)
    form_first.queue_saved_company_analysis(db, collection, accepted)
    company = db.scalar(
        select(Company).where(
            Company.project_id == project_id,
            Company.domain == "newfixture.test",
        )
    )
    observation = db.scalar(
        select(LeadSourceObservation).where(LeadSourceObservation.company_id == company.id)
    )
    assert company.company_name == "株式会社Fixture"
    assert company.source == "form_first"
    assert company.contact_url == "https://newfixture.test/contact"
    assert company.form_first_contact_url == "https://newfixture.test/contact"
    assert company.corporate_number == ""
    assert observation.source == "form_first"
    assert observation.facts["site_discovery"]["form_first_fields"]["company_name"][
        "source_url"
    ].endswith("/company")
    db.refresh(hit)
    assert hit.form_first_metadata["form_first_candidate"] is True
    assert hit.form_first_metadata["form_first_corporate_check"] == "CORPORATE_CHECK_SKIPPED"
    assert hit.form_first_metadata["form_first_form_status"] == "FORM_FOUND"
    assert "form_first_candidate" not in hit.snapshot
    assert reused and "<form>" in reused[0]
    assert not db.scalar(
        select(OperationJob.id).where(OperationJob.operation_type == "site_analysis")
    )


def test_reservation_only_company_is_registered_but_blocked_from_send_readiness(
    auth, db, monkeypatch
):
    project = make_project(auth)
    project_id = UUID(project["id"])
    collection = start_job(db, project_id, "serper", "intitle:お問い合わせ", "名古屋市")
    hit = CollectionDiscoveryHit(
        collection_job_id=collection.id,
        position=1,
        snapshot={"link": "https://reservation-fixture.test/contact", "title": "お問い合わせ"},
        raw_hash="c" * 64,
        classification="OFFICIAL_SITE_CANDIDATE",
        classification_reason="OFFICIAL_IDENTITY_NOT_VERIFIED",
        disposition="CAPTURED",
        retain_until=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(hit)
    db.commit()
    pages = {
        "https://reservation-fixture.test/contact": """
        <html><head><title>店舗予約</title></head><body><h1>ご予約</h1>
        <form><label>来店日<input type="date" name="visit_date"></label>
        <label>人数<input name="party_size"></label><input type="email" name="email">
        <button type="submit">予約する</button></form></body></html>
        """,
        "https://reservation-fixture.test/": """
        <table><tr><th>会社名</th><td>株式会社Fixture</td></tr>
        <tr><th>事業内容</th><td>飲食店の運営</td></tr></table>
        """,
    }

    class Fetcher:
        def __init__(self):
            self.site_root = ""

        def fetch_html(self, url):
            return FetchedPage(url, pages[url])

        def close(self):
            return None

    monkeypatch.setattr(form_first, "SafeFetcher", Fetcher)
    monkeypatch.setattr(form_first, "_minimum_host_interval", lambda _host: None)
    monkeypatch.setattr(
        form_first,
        "lookup_corporate_number",
        lambda *_args: {
            "status": "CORPORATE_CHECK_SKIPPED",
            "corporate_number": "",
        },
    )
    result = Candidate(
        "お問い合わせ",
        "https://reservation-fixture.test/contact",
        discovery_hit_id=hit.id,
    )
    accepted = form_first.process_search_results(
        db,
        collection,
        [result],
        {"form_first_query_map": {}},
        lambda: False,
    )
    assert len(accepted) == 1
    assert accepted[0].site_discovery["form_first_form_status"] == "RESERVATION_FORM"
    save_candidates(db, collection, accepted, "intitle:お問い合わせ")
    form_first.queue_saved_company_analysis(db, collection, accepted)

    company = db.scalar(
        select(Company).where(
            Company.project_id == project_id,
            Company.domain == "reservation-fixture.test",
        )
    )
    profile = db.scalar(select(FormProfile).where(FormProfile.company_id == company.id))
    assert company.source == "form_first"
    assert company.contact_url == ""
    assert company.form_first_contact_url == ""
    assert company.reference_url == "https://reservation-fixture.test/contact"
    assert profile.compatibility_reason_code == "RESERVATION_FORM"
    assert profile.fingerprint == ""
    assert (
        db.scalar(select(OperationJob.id).where(OperationJob.operation_type == "form_intelligence"))
        is None
    )

    from app import form_dm_readiness_routes as readiness

    monkeypatch.setattr(
        readiness,
        "evaluate_contact_permission",
        lambda *_args: SimpleNamespace(reason_code="allowed"),
    )
    monkeypatch.setattr(readiness, "duplicate", lambda *_args: False)
    assert readiness.classify_profile(db, company, profile)["primary_reason"] == "RESERVATION_FORM"


def test_robots_rejection_stops_before_company_pages(monkeypatch):
    class Fetcher:
        def __init__(self):
            pass

        def fetch_html(self, _url):
            raise ScrapeError("robots.txtにより解析が許可されていません。")

        def close(self):
            return None

    monkeypatch.setattr(form_first, "SafeFetcher", Fetcher)
    monkeypatch.setattr(form_first, "_minimum_host_interval", lambda _host: None)
    reason, pages = form_first._fetch_candidate("https://robots.test/contact")
    assert reason == "REJECT_ROBOTS"
    assert pages == []
