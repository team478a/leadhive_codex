"""Synthetic TLS server owned by this process; never dials an external address."""

from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler
from threading import Event
from unittest.mock import patch

import fetch
import transport
from test_observer import HTML
from test_transport import TLSFixture

SCENARIOS = (
    "success",
    "robots-denied",
    "http-rejected",
    "response-invalid",
    "timeout",
    "tls-failed",
)


class OwnedFixture:
    def __init__(self, scenario: str = "success"):
        if scenario not in SCENARIOS:
            raise ValueError("Unsupported synthetic scenario")
        self.scenario = scenario
        self.closed = Event()
        self.stack = ExitStack()

    def __enter__(self):
        self.lab = TLSFixture()
        self.stack.callback(self.lab.close)
        self.lab.server.daemon_threads = True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.lab.events.append(
                    (self.command, self.path, dict(self.headers), b"")
                )
                if self.path not in ("/robots.txt", "/contact/"):
                    self.send_error(404)
                    return
                robots = self.path == "/robots.txt"
                body = b"User-agent: *\nAllow: /\n" if robots else HTML.encode()
                if robots and owner.scenario == "robots-denied":
                    body = b"User-agent: *\nDisallow: /contact/\n"
                if owner.scenario == "timeout" and owner.closed.wait(10):
                    return
                self.send_response(503 if owner.scenario == "http-rejected" else 200)
                self.send_header(
                    "Content-Type",
                    "text/plain" if robots else "text/html; charset=utf-8",
                )
                self.send_header("Content-Length", str(len(body)))
                if owner.scenario == "response-invalid":
                    self.send_header("Content-Encoding", "gzip")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *_):
                pass

        self.lab.server.RequestHandlerClass = Handler

        def resolve(host: str, timeout: float = 5):
            if host != "managed.example":
                raise transport.TransportBlocked("Only synthetic host allowed")
            return ("8.8.8.8",)

        def dial(address: str, timeout: float):
            if address != "8.8.8.8":
                raise transport.TransportBlocked("Only synthetic pin allowed")
            return self.lab.dial(address, timeout)

        self.stack.enter_context(
            patch.object(fetch.transport, "resolve", side_effect=resolve)
        )
        self.stack.enter_context(
            patch.object(fetch.transport, "dial", side_effect=dial)
        )
        return self

    def __exit__(self, *_):
        self.closed.set()
        self.stack.close()
