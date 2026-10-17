import asyncio
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

import pytest

from browser_worker.network_proxy import BrowserNetworkPolicy
from browser_worker.safety import (
    BrowserPreflightBlocked,
    _RequiredProxyHandler,
    open_page_after_preflight,
)


def test_robots_proxy_cannot_be_bypassed_by_no_proxy(monkeypatch):
    def no_bypass(_host):
        raise AssertionError("ProxyHandler consulted NO_PROXY")

    monkeypatch.setattr(urllib.request, "proxy_bypass", no_bypass)
    handler = _RequiredProxyHandler({"https": "http://127.0.0.1:3128"})
    request = urllib.request.Request("https://forms.example.test/robots.txt")

    assert handler.proxy_open(request, "http://127.0.0.1:3128", "https") is None
    assert request.host == "127.0.0.1:3128"


class _RobotsHandler(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        type(self).requests.append(self.path)
        body = b"User-agent: *\nDisallow: /contact\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def test_robots_denial_precedes_any_page_navigation():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RobotsHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address

    class LocalOpener:
        def open(self, _request, timeout):
            return urlopen(f"http://{host}:{port}/robots.txt", timeout=timeout)

    def local_opener_factory(*_handlers):
        return LocalOpener()

    class Page:
        called = False

        async def goto(self, *_args, **_kwargs):
            self.called = True

    class TestPolicy(BrowserNetworkPolicy):
        def allows(self, hostname):
            return hostname == "forms.example.test"

    page = Page()
    try:
        from browser_worker.safety import robots_allowed_before_navigation

        def checker(url, policy, proxy_url):
            return robots_allowed_before_navigation(
                url, policy, proxy_url, opener_factory=local_opener_factory
            )

        allowed = checker(
            "https://forms.example.test/contact",
            TestPolicy("forms.example.test"),
            "http://127.0.0.1:1",
        )
        assert allowed is False
        with pytest.raises(BrowserPreflightBlocked, match="robots.txt does not allow"):
            asyncio.run(
                open_page_after_preflight(
                    page,
                    "https://forms.example.test/contact",
                    TestPolicy("forms.example.test"),
                    "http://127.0.0.1:1",
                    preflight_checker=checker,
                )
            )
        assert page.called is False
        assert _RobotsHandler.requests == ["/robots.txt", "/robots.txt"]
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
