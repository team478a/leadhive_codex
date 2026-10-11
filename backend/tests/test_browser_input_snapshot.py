import hashlib

import httpx
import pytest

from app.services import browser_input_snapshot as snapshots
from app.services import scraper
from app.services.scraper import ScrapeError


@pytest.fixture
def mock_fetch(monkeypatch):
    requests = []
    routes = {}
    original = scraper.SafeFetcher.__init__

    def handler(request):
        requests.append(request)
        status, kind, body = routes.get(str(request.url), (404, "text/plain", ""))
        if status in {301, 302}:
            return httpx.Response(status, headers={"location": body})
        return httpx.Response(status, headers={"content-type": kind}, text=body)

    def initialize(self):
        original(self)
        self.client.close()
        self.client = httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(scraper.SafeFetcher, "__init__", initialize)
    monkeypatch.setattr(scraper, "_validated_target", lambda url: (url, "example.com"))
    monkeypatch.setattr(scraper.time, "sleep", lambda value: None)
    routes["https://example.com/robots.txt"] = (200, "text/plain", "User-agent: *\nAllow: /")
    return routes, requests


def test_get_bundle_hashes_provenance_and_bounded_same_origin_assets(mock_fetch):
    routes, requests = mock_fetch
    routes["https://example.com/contact"] = (
        200,
        "text/html",
        '<script src="/render.js"></script><link rel="stylesheet" href="/theme.css">',
    )
    routes["https://example.com/render.js"] = (200, "text/javascript", "/* synthetic */")
    routes["https://example.com/theme.css"] = (200, "text/css", "form{display:block}")
    result = snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert result["status"] == "SNAPSHOT_READY"
    assert result["getRequests"] == len(requests) == 4
    assert all(request.method == "GET" for request in requests)
    assert result["bundle"]["permission"] == "UNKNOWN"
    assert (
        result["bundle"]["resources"][0]["sha256"] == hashlib.sha256(b"/* synthetic */").hexdigest()
    )
    assert result["observedAt"]


def test_sales_prohibition_stops_before_assets(mock_fetch):
    routes, requests = mock_fetch
    routes["https://example.com/contact"] = (
        200,
        "text/html",
        '営業目的のお問い合わせは禁止です。<script src="/render.js"></script>',
    )
    result = snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert result["status"] == "BLOCKED"
    assert result["bundle"] is None
    assert len(requests) == 2


def test_third_party_assets_are_never_acquired(mock_fetch):
    routes, requests = mock_fetch
    routes["https://example.com/contact"] = (
        200,
        "text/html",
        '<script src="https://foreign.example/script.js"></script>',
    )
    result = snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert result["bundle"]["resources"] == []
    assert len(requests) == 2


def test_resource_budget_does_not_fetch_all_assets(mock_fetch):
    routes, requests = mock_fetch
    routes["https://example.com/contact"] = (
        200,
        "text/html",
        "".join(f'<script src="/{i}.js"></script>' for i in range(9)),
    )
    with pytest.raises(ScrapeError, match="リソース数"):
        snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert len(requests) == 2


def test_mime_mismatch_fails_closed(mock_fetch):
    routes, requests = mock_fetch
    routes["https://example.com/contact"] = (
        200,
        "text/html",
        '<script src="/render.js"></script>',
    )
    routes["https://example.com/render.js"] = (200, "text/html", "not javascript")
    with pytest.raises(ScrapeError, match="Content-Type"):
        snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert len(requests) == 3


def test_robots_prohibition_blocks_asset(mock_fetch):
    routes, requests = mock_fetch
    routes["https://example.com/contact"] = (
        200,
        "text/html",
        '<script src="/render.js"></script>',
    )
    routes["https://example.com/robots.txt"] = (
        200,
        "text/plain",
        "User-agent: *\nDisallow: /render.js",
    )
    with pytest.raises(ScrapeError, match="robots"):
        snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert len(requests) == 2


def test_private_url_and_unconfirmed_terms_never_open_client(monkeypatch):
    def no_client(self):
        raise AssertionError("Must not open an HTTP client")

    monkeypatch.setattr(scraper.SafeFetcher, "__init__", no_client)
    with pytest.raises(ScrapeError):
        snapshots.acquire_snapshot("https://127.0.0.1/contact", terms_confirmed=True)
    with pytest.raises(ScrapeError, match="利用条件"):
        snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=False)


@pytest.mark.parametrize(
    "redirect", ["https://foreign.example/contact", "http://example.com/contact"]
)
def test_initial_redirect_cannot_escape_site_or_downgrade(mock_fetch, redirect):
    routes, requests = mock_fetch
    routes["https://example.com/contact"] = (302, "text/html", redirect)
    with pytest.raises(ScrapeError):
        snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert len(requests) == 2


def test_acquisition_closes_client_on_budget_failure(mock_fetch, monkeypatch):
    routes, _ = mock_fetch
    routes["https://example.com/contact"] = (
        200,
        "text/html",
        '<script src="/render.js"></script>',
    )
    routes["https://example.com/render.js"] = (200, "text/javascript", "x" * 100)
    monkeypatch.setattr(snapshots, "MAX_BUNDLE_BYTES", 50)
    closed = []
    original = scraper.SafeFetcher.close

    def close(self):
        closed.append(True)
        original(self)

    monkeypatch.setattr(scraper.SafeFetcher, "close", close)
    with pytest.raises(ScrapeError, match="合計サイズ"):
        snapshots.acquire_snapshot("https://example.com/contact", terms_confirmed=True)
    assert closed == [True]
