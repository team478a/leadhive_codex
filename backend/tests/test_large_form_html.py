"""Network-free regression for large image-bearing form discovery pages."""

import httpx
import pytest
from bs4 import BeautifulSoup

from app.services import scraper
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_intelligence.rules import sales_contact_status


def markup(image_size=2_050_000):
    return (
        '<html><body><img alt="会社写真" src="data:image/png;base64,'
        + "A" * image_size
        + '"><p>営業目的のお問い合わせはお断りします</p>'
        '<a href="/contact">お問い合わせ</a><script src="recaptcha.js"></script>'
        '<form action="/submit" method="post"><input name="email" type="email" required>'
        '<input name="token" type="hidden" value="original">'
        '<textarea name="message" required></textarea></form></body></html>'
    )


def fetch(monkeypatch, html, *, compact=True, declared=True):
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    monkeypatch.setattr(scraper.time, "sleep", lambda _: None)
    f = scraper.FormDiscoveryFetcher() if compact else scraper.SafeFetcher()
    f.client.close()
    calls = []

    def response(request):
        calls.append((request.method, str(request.url)))
        body = b"" if request.url.path == "/robots.txt" else html.encode()
        result = httpx.Response(
            200, content=body, headers={"Content-Type": "text/html; charset=utf-8"}
        )
        if not declared and "content-length" in result.headers:
            del result.headers["content-length"]
        return result

    f.client = httpx.Client(transport=httpx.MockTransport(response))
    try:
        return f.fetch_html("https://example.com/"), calls
    finally:
        f.close()


@pytest.mark.parametrize("declared", [True, False])
def test_large_image_preserves_footer_form_and_prohibition(monkeypatch, declared):
    original = markup()
    page, calls = fetch(monkeypatch, original, declared=declared)
    assert len(page.html.encode()) < 2_000_000
    assert calls == [("GET", "https://example.com/robots.txt"), ("GET", "https://example.com/")]
    assert BeautifulSoup(page.html, "html.parser").a["href"] == "/contact"
    before = BeautifulSoup(original, "html.parser")
    after = BeautifulSoup(page.html, "html.parser")
    assert str(before.form) == str(after.form)
    assert parse_form_fields(before.form) == parse_form_fields(after.form)
    assert form_fingerprint(parse_form_fields(before.form)) == form_fingerprint(
        parse_form_fields(after.form)
    )
    assert before.script == after.script
    assert sales_contact_status(after.get_text(" ", strip=True), True)[0] == "PROHIBITED"


def test_standard_fetcher_keeps_original_size_guard(monkeypatch):
    with pytest.raises(scraper.ScrapeError, match="データサイズ"):
        fetch(monkeypatch, markup(), compact=False)


@pytest.mark.parametrize("declared", [True, False])
@pytest.mark.parametrize(
    "body", [markup(8_000_001), "<p>" + "A" * 2_100_000 + "</p>"], ids=["raw-cap", "text-cap"]
)
def test_hard_cap_and_non_image_overflow_never_return_partial(monkeypatch, body, declared):
    with pytest.raises(scraper.ScrapeError, match="データサイズ"):
        fetch(monkeypatch, body, declared=declared)


def test_small_page_is_byte_for_byte_unchanged(monkeypatch):
    original = markup(10)
    page, _ = fetch(monkeypatch, original)
    assert page.html == original


def test_only_raster_img_src_is_removed():
    original = markup(5000) + '<input value="data:image/png;base64,' + "B" * 5000 + '">'
    original += '<img src="data:image/svg+xml;base64,' + "C" * 5000 + '">'
    after = BeautifulSoup(scraper.compact_discovery_images(original), "html.parser")
    assert after.img["src"] == "data:,"
    assert after.find_all("input")[-1]["value"].endswith("B" * 5000)
    assert after.find_all("img")[-1]["src"].endswith("C" * 5000)


def test_robots_block_still_prevents_document_fetch(monkeypatch):
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    f = scraper.FormDiscoveryFetcher()
    f.client.close()
    calls = []

    def response(request):
        calls.append(str(request.url))
        return httpx.Response(
            200, text="User-agent: *\nDisallow: /", headers={"Content-Type": "text/plain"}
        )

    f.client = httpx.Client(transport=httpx.MockTransport(response))
    try:
        with pytest.raises(scraper.ScrapeError, match="robots"):
            f.fetch_html("https://example.com/")
        assert calls == ["https://example.com/robots.txt"]
    finally:
        f.close()


def test_compaction_redirect_keeps_site_boundary(monkeypatch):
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    monkeypatch.setattr(scraper.time, "sleep", lambda _: None)
    f = scraper.FormDiscoveryFetcher()
    f.site_root = "https://example.com/"
    f.client.close()
    calls = []

    def response(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://outside.example/contact"})

    f.client = httpx.Client(transport=httpx.MockTransport(response))
    try:
        with pytest.raises(scraper.ScrapeError, match="別サイト"):
            f.fetch_html("https://example.com/")
        assert calls == ["https://example.com/robots.txt", "https://example.com/"]
    finally:
        f.close()


def test_compaction_keeps_request_budget(monkeypatch):
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    f = scraper.FormDiscoveryFetcher()
    f._request_count = 32
    try:
        with pytest.raises(scraper.ScrapeError, match="回数・時間上限"):
            f.fetch_html("https://example.com/")
    finally:
        f.close()
