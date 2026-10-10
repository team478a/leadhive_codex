import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.config import settings
from app.services import scrapling_adapter as adapter
from app.services.scraper import FetchedPage, ScrapeError, extract_page
from offline_replay.scrapling_metrics import summarize

URL = "https://scrapling-fixture.invalid/"
HTML = """<html><head><meta property="og:site_name" content="試験株式会社"></head>
<body><p>兵庫県姫路市本町1-1 電話 079-123-4567</p>
<a href="/contact">お問い合わせ</a>
<a href="https://instagram.com/fixture">Instagram</a></body></html>"""


@pytest.fixture(autouse=True)
def flag(monkeypatch):
    monkeypatch.setattr(settings, "scrapling_probe_enabled", True)


def test_default_off_prevents_fetch_and_optional_import(monkeypatch):
    monkeypatch.setattr(settings, "scrapling_probe_enabled", False)
    with pytest.raises(adapter.ProbeUnavailable, match="DISABLED"):
        adapter.acquire(URL)
    with pytest.raises(adapter.ProbeUnavailable, match="DISABLED"):
        adapter.probe(FetchedPage(URL, HTML), "scrapling_static")


def test_static_reuses_pagedata_and_evidence():
    result = adapter.probe(FetchedPage(URL, HTML), "scrapling_static")
    assert result.data is not None
    assert result.data.company_name == "試験株式会社"
    assert result.data.contact_url == URL + "contact"
    assert result.data.phone == "079-123-4567"
    assert result.data.instagram_url == "https://instagram.com/fixture"
    assert not result.data.field_evidence["company_name"]["verified"]


def test_robots_failure_not_retried_by_scrapling(monkeypatch):
    def denied(self, url):
        self._request_count = 1
        raise ScrapeError("robots.txtにより解析が許可されていません。")

    monkeypatch.setattr(adapter.SafeFetcher, "fetch_html", denied)
    with pytest.raises(ScrapeError) as caught:
        adapter.acquire(URL)
    assert caught.value.probe_external_gets == 1
    assert adapter.acquisition_failure(caught.value) == "ROBOTS_BLOCKED_OR_UNAVAILABLE"


def test_get_budget_prevents_redirect_loop(monkeypatch):
    monkeypatch.setattr(
        adapter.SafeFetcher, "fetch_html", lambda self, url: self._request(url, 100)
    )

    def looping(self, *args, **kwargs):
        self._request_count += 1
        return self._request(*args, **kwargs)

    monkeypatch.setattr(adapter.SafeFetcher, "_request", looping)
    with pytest.raises(ScrapeError) as caught:
        adapter.acquire(URL)
    assert caught.value.probe_external_gets == 8


def test_oversize_input_and_unknown_mode():
    assert (
        adapter.probe(
            FetchedPage(URL, "a" * (settings.scraper_max_bytes + 1)), "scrapling_static"
        ).failure_reason
        == "INPUT_TOO_LARGE"
    )
    assert adapter.probe(FetchedPage(URL, HTML), "bad").failure_reason == "UNKNOWN_MODE"


def test_dynamic_inline_js_and_network_block():
    html = """<html><head><title>JS試験会社</title></head><body><script>
    fetch('http://127.0.0.1:80/private').catch(() => {});
    const img = new Image(); img.src = 'http://127.0.0.1:80/private';
    document.body.innerHTML += '<a href="/contact">お問い合わせ</a>';
    </script></body></html>"""
    assert not extract_page(html, URL).contact_url
    result = adapter.probe(FetchedPage(URL, html), "scrapling_dynamic_replay")
    assert result.data is not None, result.failure_reason
    assert result.data.contact_url == URL + "contact"
    assert result.blocked_browser_requests >= 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "https://user:password@example.com/",
        "https://example.com:8443/",
    ],
)
def test_unsafe_live_targets_never_reach_scrapling(url):
    with pytest.raises(ScrapeError) as caught:
        adapter.acquire(url)
    assert caught.value.probe_external_gets == 0
    assert adapter.acquisition_failure(caught.value) == "TARGET_SAFETY_REJECTED"


def test_browser_cannot_send_to_owned_server():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append("GET")
            self.send_response(200)
            self.end_headers()

        def do_POST(self):
            hits.append("POST")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = f"http://127.0.0.1:{server.server_port}/"
    try:
        html = f"""<html><body><form action="{target}" method="post"></form>
        <script>
        fetch('{target}', {{method:'POST'}}).catch(() => {{}});
        document.forms[0].submit();
        const img = new Image(); img.src = '{target}';
        navigator.sendBeacon('{target}', 'test');
        </script></body></html>"""
        result = adapter.probe(FetchedPage(URL, html), "scrapling_dynamic_replay")
        assert result.data is not None, result.failure_reason
        assert hits == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_renderer_setup_failure_is_rejected(monkeypatch):
    from scrapling.fetchers import DynamicFetcher

    from app.services.scrapling_render_worker import render

    class Response:
        url = URL
        body = HTML.encode()

    def swallowed_hook(url, **kwargs):
        # Simulate upstream swallowing the page_setup failure.
        assert kwargs["proxy"].startswith("http://127.0.0.1:")
        assert "--host-resolver-rules=MAP * ~NOTFOUND" in kwargs["extra_flags"]
        assert kwargs["additional_args"]["service_workers"] == "block"
        return Response()

    monkeypatch.setattr(DynamicFetcher, "fetch", swallowed_hook)
    with pytest.raises(ValueError, match="INCOMPLETE"):
        render(URL, HTML)


def test_truth_and_zero_denominator_are_not_fabricated():
    result = summarize([])
    assert result["methods"]["current"]["success_rate"] is None
    row = {
        "html_acquired": True,
        "methods": {
            "current": {
                "success": True,
                "fields": {"company_name": "PRIVATE"},
                "elapsed_seconds": 1,
            },
        },
        "truth": {"company_name": "PRIVATE", "human_verified": False},
    }
    result = summarize([row])
    assert result["methods"]["current"]["human_accuracy"]["company_name"]["accuracy"] is None
    assert result["estimated_processing_cost"] is None
    assert result["correct_sales_target_information_companies"] is None
    assert "PRIVATE" not in json.dumps(result)


def test_human_labels_include_fetch_failures_in_denominator():
    truth = {
        "human_verified": True,
        "reviewer": "human",
        "reviewed_at": "2026-10-10",
        "phone": "079-123-4567",
    }
    result = summarize(
        [
            {
                "truth": truth,
                "methods": {"current": {"success": True, "fields": {"phone": "0791234567"}}},
            },
            {"truth": truth, "methods": {"current": {"success": False}}},
        ]
    )
    assert result["methods"]["current"]["human_accuracy"]["phone"]["accuracy"] == 0.5
