from types import SimpleNamespace

import httpx
import pytest

from app.services import scraper
from app.services.lead_identity import website_match
from app.services.scraper import SafeFetcher, ScrapeError, extract_page


def test_assets_fax_fullwidth_and_service_area_negative_cases():
    data = extract_page(
        "<title>Example</title><p>対応エリア 大阪府大阪市 兵庫県姫路市</p>"
        "<p>FAX: 079-123-4567 TEL：０７９（９８７）６５４３</p>"
        "<p>logo@2x.png image@retina.svg</p>",
        "https://example.com",
    )
    assert data.email == ""
    assert data.phone == "079-987-6543"
    assert data.address == ""
    assert data.field_evidence["phone"]["verified"] is False
    assert data.field_evidence["phone"]["source_url"] == "https://example.com"


def test_json_graph_address_precedes_service_area_and_title():
    data = extract_page(
        """<title>Wrong title</title><script type="application/ld+json">
    {"@graph":[{"@type":"Organization","name":"株式会社店舗",
    "address":{"addressRegion":"兵庫県","addressLocality":"姫路市",
    "streetAddress":"本町1-2-3"}}]}</script>
    <p>対応地域 大阪府大阪市</p><a href="mailto:info%40example.com?subject=test">メール</a>
    """,
        "https://example.com",
    )
    assert data.company_name == "株式会社店舗"
    assert data.address == "兵庫県姫路市本町1-2-3"
    assert data.email == "info@example.com"
    assert data.field_evidence["address"]["method"] == "JSON_LD_ADDRESS"


def test_directory_does_not_extract_first_organization():
    data = extract_page(
        """<title>一覧</title><script type="application/ld+json">
    [{"@type":"Organization","name":"A","address":{"addressRegion":"大阪府"}},
    {"@type":"Organization","name":"B","address":{"addressRegion":"兵庫県"}}]
    </script>""",
        "https://example.com",
    )
    assert data.company_name == "一覧"
    assert data.address == ""


def test_phone_conflict_and_metadata_alone_do_not_confirm():
    company = SimpleNamespace(company_name="株式会社店舗", address="", phone="0791112222")
    data = extract_page(
        "<title>株式会社店舗</title><p>TEL: 079-333-4444</p>", "https://example.com"
    )
    status, reasons = website_match(company, data)
    assert status == "REVIEW_REQUIRED" and "PHONE_CONFLICT" in reasons
    company.phone = ""
    assert website_match(company, data)[0] == "REVIEW_REQUIRED"


def test_redirect_checks_destination_robots_and_counts_all_requests(monkeypatch):
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    monkeypatch.setattr(scraper.time, "sleep", lambda seconds: None)
    calls = []

    def response(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(302, headers={"location": "/private"})

    fetcher = SafeFetcher()
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(response))
    try:
        with pytest.raises(ScrapeError, match="転送先"):
            fetcher.fetch_html("https://example.com/")
        assert calls == ["https://example.com/robots.txt", "https://example.com/"]
        assert fetcher._request_count == 2
        fetcher._request_count = 32
        with pytest.raises(ScrapeError, match="上限"):
            fetcher._request("https://example.com/contact", 1000)
        assert len(calls) == 2
    finally:
        fetcher.close()


def test_directory_mentions_target_but_does_not_become_official():
    company = SimpleNamespace(company_name="株式会社店舗", address="", phone="0791112222")
    data = extract_page(
        "<title>比較サイト</title><p>株式会社店舗 TEL: 079-111-2222</p>", "https://example.com"
    )
    status, reasons = website_match(company, data)
    assert status == "REVIEW_REQUIRED"
    assert "COMPANY_NAME_CONFLICT" in reasons


@pytest.mark.parametrize(
    "target", ["https://outside.example/contact", "http://example.com/contact"]
)
def test_secondary_redirect_is_rejected_before_external_get(monkeypatch, target):
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    monkeypatch.setattr(scraper.time, "sleep", lambda seconds: None)
    calls = []

    def response(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(302, headers={"location": target})

    fetcher = SafeFetcher()
    fetcher.client.close()
    fetcher.client = httpx.Client(transport=httpx.MockTransport(response))
    fetcher.site_root = "https://example.com/"
    try:
        with pytest.raises(ScrapeError, match="追加探索"):
            fetcher.fetch_html("https://example.com/contact")
        assert calls == ["https://example.com/robots.txt", "https://example.com/contact"]
        assert target not in calls
    finally:
        fetcher.close()


def test_robots_fetch_failure_remains_fail_closed_with_correct_reason(monkeypatch):
    fetcher = SafeFetcher()
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))

    def failure(*args, **kwargs):
        raise ScrapeError("Webサイトを取得できませんでした（HTTP 503）。")

    monkeypatch.setattr(fetcher, "_request", failure)
    try:
        with pytest.raises(ScrapeError, match="503"):
            fetcher.fetch_html("https://example.com/")
    finally:
        fetcher.close()


def test_slow_stream_stops_at_elapsed_deadline(monkeypatch):
    clock = [1.0]

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"<html>"
            clock[0] = 62.0
            yield b"<form></form>"

    monkeypatch.setattr(scraper.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    fetcher = SafeFetcher()
    monkeypatch.setattr(fetcher, "robots_allowed", lambda url: True)
    fetcher.client.close()
    fetcher.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/html"}, stream=Stream()
            )
        )
    )
    try:
        with pytest.raises(ScrapeError, match="時間上限"):
            fetcher.fetch_html("https://example.com/")
    finally:
        fetcher.close()
