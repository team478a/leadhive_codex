"""Actual loopback TLS only; DNS and numeric dial are test-owned substitutions."""

import json
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from app.services import form_pinned_get as get
from app.services import pinned_dns as dns
from app.services import pinned_read_transport as wire
from app.services.scraper import ScrapeError

LAB = Path(__file__).resolve().parents[2] / "scripts" / "pinned_tls_lab"
sys.path.insert(0, str(LAB))
from test_transport import TLSFixture  # noqa: E402

URL = "https://managed.example/contact/"
PRODUCTION_TLS_CONTEXT = get.tls_context


@pytest.fixture
def endpoint(monkeypatch):
    lab = TLSFixture()
    routes = {
        "/robots.txt": (200, [("Content-Type", "text/plain")], b"User-agent: *\nAllow: /\n"),
        "/contact/": (200, [("Content-Type", "text/html; charset=utf-8")], b"<form></form>"),
    }
    delay = [0.0]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            lab.events.append((self.command, self.path, dict(self.headers), b""))
            status, headers, body = routes[self.path]
            if delay[0]:
                time.sleep(delay[0])
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            if not any(k.lower() in {"content-length", "transfer-encoding"} for k, _ in headers):
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "PRIVATE=never-forward")
            self.end_headers()
            try:
                if ("Transfer-Encoding", "chunked") in headers:
                    self.wfile.write(("%x\r\n" % len(body)).encode() + body + b"\r\n0\r\n\r\n")
                else:
                    self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *_):
            pass

    lab.server.RequestHandlerClass = Handler
    calls = []
    monkeypatch.setattr(wire, "resolve", lambda *args: calls.append(args) or ("8.8.8.8",))
    monkeypatch.setattr(wire, "dial", lab.dial)
    monkeypatch.setattr(get, "tls_context", lambda: lab.context)
    try:
        yield lab, routes, calls, delay
    finally:
        lab.close()


def test_exact_get_pin_once_sni_host_no_cookie_proxy_or_post(endpoint, monkeypatch):
    lab, _, calls, _ = endpoint
    monkeypatch.setenv("HTTPS_PROXY", "http://PRIVATE.invalid:9")
    result = get.TargetFetcher().fetch_html(URL)
    assert result.url == URL and result.html == "<form></form>"
    assert len(calls) == 1
    assert lab.dials == ["8.8.8.8", "8.8.8.8"]
    assert lab.sni == ["managed.example", "managed.example"]
    assert [e[:2] for e in lab.events] == [("GET", "/robots.txt"), ("GET", "/contact/")]
    for _, _, headers, body in lab.events:
        assert headers["Host"] == "managed.example"
        assert "Cookie" not in headers and "Authorization" not in headers and body == b""


@pytest.mark.parametrize(
    "url",
    [
        "http://managed.example/contact/",
        "https://127.0.0.1/contact/",
        URL + "?secret=PRIVATE",
        URL + "#form",
        "https://u:p@managed.example/contact/",
        "https://managed.example:444/contact/",
        "https://managed.example/a/../contact/",
        URL + "%2f",
    ],
)
def test_invalid_target_has_no_dns_or_dial(endpoint, url):
    lab, _, calls, _ = endpoint
    with pytest.raises(ScrapeError, match="TARGET_REJECTED"):
        get.TargetFetcher().fetch_html(url)
    assert calls == [] and lab.dials == [] and lab.events == []


@pytest.mark.parametrize(
    "answer",
    [
        ("8.8.8.8", "127.0.0.1"),
        ("10.0.0.1",),
        ("::1",),
        ("::ffff:8.8.8.8",),
        ("64:ff9b::808:808",),
        ("224.0.0.1",),
        (),
    ],
)
def test_dns_private_or_mixed_results_stop_before_socket(endpoint, monkeypatch, answer):
    lab = endpoint[0]
    monkeypatch.setattr(wire, "resolve", lambda *args: answer)
    with pytest.raises(ScrapeError):
        get.TargetFetcher().fetch_html(URL)
    assert lab.dials == [] and lab.events == []


@pytest.mark.parametrize(
    "path,status",
    [
        ("/robots.txt", 302),
        ("/contact/", 301),
        ("/robots.txt", 404),
        ("/contact/", 500),
    ],
)
def test_no_redirect_retry_or_missing_robots_fallback(endpoint, path, status):
    lab, routes, _, _ = endpoint
    _, headers, body = routes[path]
    routes[path] = (status, headers + [("Location", "https://127.0.0.1/PRIVATE")], body)
    with pytest.raises(ScrapeError, match="HTTP_REJECTED"):
        get.TargetFetcher().fetch_html(URL)
    assert len(lab.events) == (1 if path == "/robots.txt" else 2)


@pytest.mark.parametrize(
    "policy",
    [
        b"User-agent: *\nDisallow: /contact/\n",
        b"User-agent: *\nAllow: /contact/\nDisallow: /\n",
        b"User-agent: *\nDisallow: /\n\nUser-agent: LeadHiveFormObserver\nAllow: /\n",
    ],
)
def test_robots_prohibition_wins_and_contact_not_requested(endpoint, policy):
    lab, routes, _, _ = endpoint
    routes["/robots.txt"] = (200, [("Content-Type", "text/plain")], policy)
    with pytest.raises(ScrapeError, match="ROBOTS_DENIED"):
        get.TargetFetcher().fetch_html(URL)
    assert len(lab.events) == 1


@pytest.mark.parametrize(
    "policy",
    [
        b"",
        b"Disallow: /",
        b"User-agent: *\nCrawl-delay: 5",
        b"User-agent: *\nDisallow: /*",
        b"User-agent: OtherBot\nAllow: /",
    ],
)
def test_unsupported_robots_stops(endpoint, policy):
    lab, routes, _, _ = endpoint
    routes["/robots.txt"] = (200, [("Content-Type", "text/plain")], policy)
    with pytest.raises(ScrapeError, match="ROBOTS_INVALID"):
        get.TargetFetcher().fetch_html(URL)
    assert len(lab.events) == 1


@pytest.mark.parametrize(
    "headers,body",
    [
        ([("Content-Type", "text/html"), ("Content-Encoding", "gzip")], b"x"),
        ([("Content-Type", "application/json")], b"{}"),
        ([("Content-Type", "text/html"), ("Content-Type", "text/plain")], b"x"),
        ([("Content-Type", "text/html")], b"x" * 262145),
        ([("Content-Type", "text/html")], b"\xff"),
    ],
    ids=["gzip", "json", "duplicate-media", "large", "invalid-utf8"],
)
def test_response_bounds_media_encoding_and_utf8(endpoint, headers, body):
    endpoint[1]["/contact/"] = (200, headers, body)
    with pytest.raises(ScrapeError, match="RESPONSE_INVALID"):
        get.TargetFetcher().fetch_html(URL)


def test_bounded_chunked_response_is_supported(endpoint):
    endpoint[1]["/contact/"] = (
        200,
        [("Content-Type", "text/html"), ("Transfer-Encoding", "chunked")],
        b"<form></form>",
    )
    assert get.TargetFetcher().fetch_html(URL).html == "<form></form>"


def test_tls_verification_cannot_be_disabled(endpoint):
    endpoint[0].context.check_hostname = False
    with pytest.raises(ScrapeError):
        get.TargetFetcher().fetch_html(URL)
    assert endpoint[0].events == []


def test_untrusted_tls_certificate_stops_before_http(endpoint):
    endpoint[0].context = ssl.create_default_context()
    with pytest.raises(ScrapeError):
        get.TargetFetcher().fetch_html(URL)
    assert endpoint[0].events == []


def test_get_admission_budget_precedes_dns(endpoint, monkeypatch):
    gate = threading.BoundedSemaphore(1)
    gate.acquire()
    monkeypatch.setattr(get, "GET_SLOTS", gate)
    monkeypatch.setattr(get.settings, "scraper_timeout_seconds", 0.05)
    try:
        with pytest.raises(ScrapeError, match="TIMEOUT"):
            get.TargetFetcher().fetch_html(URL)
        assert endpoint[2] == [] and endpoint[0].events == []
    finally:
        gate.release()


def test_shared_deadline_stops_socket(endpoint, monkeypatch):
    endpoint[3][0] = 0.5
    monkeypatch.setattr(get.settings, "scraper_timeout_seconds", 0.2)
    start = time.monotonic()
    with pytest.raises(ScrapeError):
        get.TargetFetcher().fetch_html(URL)
    assert time.monotonic() - start < 2
    assert len(endpoint[0].events) <= 1


def test_numeric_dial_does_not_resolve_again(monkeypatch):
    calls = []

    class Socket:
        def settimeout(self, value):
            pass

        def connect(self, target):
            calls.append(target)

        def close(self):
            pass

    monkeypatch.setattr(wire.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(wire.socket, "getaddrinfo", lambda *args: pytest.fail("second DNS"))
    wire.dial("8.8.8.8", 1)
    assert calls == [("8.8.8.8", 443)]


@pytest.mark.parametrize("host", ["success.example", "env.example"])
def test_real_dns_child_codec_environment_and_cleanup(monkeypatch, tmp_path, host):
    monkeypatch.setenv("DATABASE_URL", "PRIVATE")
    monkeypatch.setenv("SMTP_PASSWORD", "PRIVATE")
    monkeypatch.setenv("HTTPS_PROXY", "PRIVATE")
    marker = tmp_path / "ready.txt"
    monkeypatch.setattr(
        dns,
        "worker_command",
        lambda host: [
            sys.executable,
            "-I",
            str(LAB / "dns_fixture.py"),
            host,
            str(marker),
        ],
    )
    assert len(dns.isolated_resolve(host)) == 2


def test_real_dns_hang_is_killed_reaped_and_slot_reusable(monkeypatch, tmp_path):
    marker = tmp_path / "ready.txt"
    monkeypatch.setattr(
        dns,
        "worker_command",
        lambda host: [
            sys.executable,
            "-I",
            str(LAB / "dns_fixture.py"),
            host,
            str(marker),
        ],
    )
    children = []
    spawn = subprocess.Popen

    def record(*args, **kwargs):
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(dns.subprocess, "Popen", record)
    with pytest.raises(dns.ResolutionTimeout):
        dns.isolated_resolve("hang.example", 0.5)
    assert children[0].poll() is not None and children[0].stdout.closed
    assert len(dns.isolated_resolve("success.example")) == 2


def test_dns_decode_rejects_ambiguous_or_excessive_results():
    for value in (
        b"",
        b"x" * 8193,
        b'{"version":1,"version":1,"addresses":["8.8.8.8"]}',
        json.dumps({"version": 1, "addresses": ["8.8.8.8"] * 65}).encode(),
    ):
        with pytest.raises(dns.ResolutionFailure):
            dns.decode(value)


def test_dns_admission_does_not_spawn(monkeypatch):
    gate = threading.BoundedSemaphore(1)
    gate.acquire()
    monkeypatch.setattr(dns, "SLOTS", gate)
    monkeypatch.setattr(dns.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected child"))
    try:
        with pytest.raises(dns.ResolutionTimeout):
            dns.isolated_resolve("managed.example", 0.05)
    finally:
        gate.release()


def test_unconfirmed_dns_cleanup_quarantines_future_lookups(monkeypatch):
    from unittest.mock import Mock

    fault = threading.Event()
    fake = Mock()
    fake.communicate.side_effect = subprocess.TimeoutExpired("fixture", 1)
    fake.poll.return_value = None
    fake.wait.side_effect = subprocess.TimeoutExpired("fixture", 1)
    monkeypatch.setattr(dns, "FAULT", fault)
    retained = []
    monkeypatch.setattr(dns, "FAILED_CHILDREN", retained)
    monkeypatch.setattr(dns.subprocess, "Popen", lambda *a, **k: fake)
    with pytest.raises(dns.ResolutionCleanupFailure):
        dns.isolated_resolve("managed.example", 0.1)
    assert fault.is_set() and retained == [fake]
    with pytest.raises(dns.ResolutionCleanupFailure):
        dns.isolated_resolve("managed.example", 0.1)


def test_application_dns_worker_codec_without_external_dns(monkeypatch):
    from app.services import pinned_dns_worker as worker

    monkeypatch.setattr(
        worker.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("8.8.8.8", 443)),
        ],
    )
    assert dns.decode(worker.lookup("managed.example")) == ("8.8.8.8",)


def test_ca_environment_cannot_add_fixture_trust(endpoint, monkeypatch):
    # A real but untrusted fixture CA exists at this path. It must not become
    # trusted just because SSL_CERT_FILE points to it.
    monkeypatch.setenv("SSL_CERT_FILE", str(Path(endpoint[0].temp.name) / "cert.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", endpoint[0].temp.name)
    monkeypatch.setattr(get, "tls_context", PRODUCTION_TLS_CONTEXT)
    with pytest.raises(ScrapeError):
        get.TargetFetcher().fetch_html(URL)
    assert endpoint[0].events == []
