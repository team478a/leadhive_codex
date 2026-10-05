"""Test-only TCP fixture. No production imports or configurable remote destination."""

import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx

HOST = "form-lab.test"
ORIGIN = f"http://{HOST}"


def html(path, changed=False, captcha=False, prohibited=False, token="fixture-token"):
    extra = '<input name="new_required" required>' if changed else ""
    extra += '<div class="g-recaptcha"></div>' if captcha else ""
    extra += "<p>営業目的の送信はお断りします</p>" if prohibited else ""
    action = path.removesuffix("contact") + "submit"
    return f'''<!doctype html><html><body><form method="post" action="{action}">
    <label for="email">email</label><input id="email" type="email" name="email" required>
    <label for="message">message</label><textarea id="message" name="message" required></textarea>
    <input type="hidden" name="csrf" value="{token}">{extra}
    <button type="submit">送信</button></form></body></html>'''


class Lab:
    def __init__(self):
        self.mode = "success"
        self.gets = 0
        self.posts = []
        self.accepted = threading.Event()
        self.preflight = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        lab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body="", **headers):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Expected when the test kills an accepted client's process.

            def do_GET(self):
                if self.path == "/robots.txt":
                    return self.reply(200, "User-agent: *\nAllow: /\n")
                if self.path.endswith("/thanks"):
                    return self.reply(200, "<p>お問い合わせを受け付けました</p>")
                if not self.path.endswith("/contact"):
                    return self.reply(404)
                with lab.lock:
                    lab.gets += 1
                    number = lab.gets
                if lab.mode == "hold_preflight":
                    lab.preflight.set()
                    lab.release.wait(20)
                return self.reply(
                    200,
                    html(
                        self.path,
                        changed=lab.mode == "changed"
                        or (lab.mode == "changed_after_inspect" and number >= 2),
                        captcha=lab.mode == "captcha",
                        prohibited=lab.mode == "prohibited",
                        token=f"fixture-token-{number}",
                    ),
                )

            def do_POST(self):
                if not self.path.endswith("/submit"):
                    return self.reply(404)
                payload = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                with lab.lock:
                    lab.posts.append({"path": self.path, "payload": payload})
                lab.accepted.set()
                if lab.mode in {"hold_accepted", "timeout"}:
                    lab.release.wait(20)
                if lab.mode == "disconnect":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if lab.mode == "truncated":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", "10000")
                    self.end_headers()
                    self.wfile.write(b"<p>partial")
                    self.close_connection = True
                    return
                if lab.mode == "ambiguous":
                    return self.reply(200, "<p>処理中です</p>")
                if lab.mode == "repost_redirect":
                    return self.reply(307, Location=self.path)
                if lab.mode == "redirect_success":
                    return self.reply(303, Location=self.path.removesuffix("submit") + "thanks")
                return self.reply(200, "<p>お問い合わせを受け付けました</p>")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class LoopbackTransport(httpx.BaseTransport):
    """Route only one reserved .test origin to real localhost TCP, never the internet."""

    def __init__(self, port):
        self.port = port
        self.inner = httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        if (
            request.url.host != HOST
            or request.url.scheme != "http"
            or request.url.port not in {None, 80}
        ):
            raise AssertionError("HTTP lab refuses every other destination")
        local = request.url.copy_with(host="127.0.0.1", port=self.port)
        forwarded = httpx.Request(
            request.method,
            local,
            headers=request.headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return self.inner.handle_request(forwarded)

    def close(self):
        self.inner.close()


@contextmanager
def local_transport(port):
    # DNS and socket routing seams exist only in this test helper. URL validation,
    # robots, parser, fingerprint, POST and result checking stay production code.
    from app.services.scraper import SafeFetcher

    original_dns = socket.getaddrinfo
    original_init = SafeFetcher.__init__

    def dns(host, port, *args, **kwargs):
        if host == HOST:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        if host not in {"127.0.0.1", "localhost"}:
            raise AssertionError("HTTP lab refuses external DNS")
        return original_dns(host, port, *args, **kwargs)

    def initialize(self):
        original_init(self)
        self.client.close()
        self.client = httpx.Client(
            transport=LoopbackTransport(port),
            timeout=5,
            trust_env=False,
            follow_redirects=False,
            headers={"User-Agent": "LeadHive-controlled-test"},
        )

    with (
        patch.object(socket, "getaddrinfo", dns),
        patch.object(SafeFetcher, "__init__", initialize),
    ):
        yield
