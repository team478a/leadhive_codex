"""Real TLS to loopback only; DNS and numeric dial are replaced by fixtures."""

import os
import time
import unittest
from http.server import BaseHTTPRequestHandler
from threading import Event
from unittest.mock import patch

import fetch as f
import transport as t
from test_observer import HTML
from test_transport import TLSFixture


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.lab = TLSFixture()
        self.addCleanup(self.lab.close)
        self.routes = {
            "/robots.txt": (
                200,
                [("Content-Type", "text/plain")],
                b"User-agent: *\nAllow: /\n",
            ),
            "/contact/": (
                200,
                [("Content-Type", "text/html; charset=utf-8")],
                HTML.encode(),
            ),
        }
        self.delay = 0
        self.cancel = Event()
        self.cancel_after_robots = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.lab.events.append(
                    (self.command, self.path, dict(self.headers), b"")
                )
                status, headers, body = owner.routes[self.path]
                if owner.delay:
                    time.sleep(owner.delay)
                self.send_response(status)
                for key, value in headers:
                    self.send_header(key, value)
                if not any(key.lower() == "content-length" for key, _ in headers):
                    self.send_header("Content-Length", str(len(body)))
                self.send_header("Set-Cookie", "fixture=never-forward")
                self.end_headers()
                if self.path == "/robots.txt" and owner.cancel_after_robots:
                    owner.cancel.set()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *_):
                pass

        self.lab.server.RequestHandlerClass = Handler
        self.env = patch.dict(os.environ, {"CF7_OBSERVER_GET_LAB": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.dns = patch.object(t, "resolve", return_value=("8.8.8.8",)).start()
        self.addCleanup(patch.stopall)
        patch.object(t, "dial", side_effect=self.lab.dial).start()

    def observe(self, **kwargs):
        return f.observe_owned_page(
            context=self.lab.context, cancelled=self.cancel, **kwargs
        )

    def test_gets_robots_then_contact_without_authority_or_credentials(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://invalid.example:99"}):
            result = self.observe()
        self.assertEqual(
            [e[:2] for e in self.lab.events],
            [("GET", "/robots.txt"), ("GET", "/contact/")],
        )
        self.assertEqual(self.lab.sni, ["managed.example"] * 2)
        self.assertEqual(self.lab.dials, ["8.8.8.8"] * 2)
        self.assertEqual(self.dns.call_count, 2)
        self.assertEqual(result.pinned_ips, ("8.8.8.8",) * 2)
        self.assertEqual(len(result.robots_sha256), 64)
        self.assertFalse(result.observation.eligible_for_approval)
        self.assertEqual(result.observation.sales_permission, "UNCERTAIN")
        self.assertEqual(result.observation.captcha_state, "UNVERIFIED")
        for _, _, headers, body in self.lab.events:
            self.assertNotIn("Cookie", headers)
            self.assertNotIn("Authorization", headers)
            self.assertEqual(headers["User-Agent"], f.USER_AGENT)
            self.assertEqual(headers["Host"], "managed.example")
            self.assertEqual(body, b"")

    def test_disabled_and_non_owned_destinations_stop_before_dns(self):
        with (
            patch.dict(os.environ, {"CF7_OBSERVER_GET_LAB": "0"}),
            self.assertRaises(t.TransportBlocked),
        ):
            self.observe()
        for url in [
            "https://real.example/contact/",
            f.PAGE + "?a=1",
            "https://127.0.0.1/",
            f.PAGE + "%2e",
            f.PAGE + "#x",
            "https://managed.example/wp-json/",
        ]:
            with self.subTest(url=url), self.assertRaises(t.TransportBlocked):
                f.observe_owned_page(url, context=self.lab.context)
        self.dns.assert_not_called()
        self.assertEqual(self.lab.events, [])

    def test_robots_denied_unknown_or_non_200_never_fetches_contact(self):
        for status, body in [
            (200, b"User-agent: *\nAllow: /\nDisallow: /contact/\n"),
            (200, b"User-agent: Other\nAllow: /\n"),
            (
                200,
                b"User-agent: *\nAllow: /\n\nUser-agent: LeadHiveObserverLab\nDisallow: /\n",
            ),
            (200, b"User-agent: *\nAllow: /\n#" + b"x" * 16384),
            (200, b"User-agent: *\nDisallow: /contact/\n"),
            (200, b"<html>not robots</html>"),
            (200, b"User-agent: *\nCrawl-delay: 10\n"),
            (200, b"User-agent: *\nDisallow: /*\n"),
            (200, b"\xff"),
            (401, b"denied"),
            (403, b"denied"),
            (404, b"missing"),
            (302, b"redirect"),
            (429, b"limit"),
            (503, b"busy"),
        ]:
            self.lab.events.clear()
            self.routes["/robots.txt"] = (
                status,
                [("Content-Type", "text/plain")],
                body,
            )
            with (
                self.subTest(status=status, body=body),
                self.assertRaises(t.TransportBlocked),
            ):
                self.observe()
            self.assertEqual([e[1] for e in self.lab.events], ["/robots.txt"])

    def test_contact_metadata_is_checked_before_static_analysis(self):
        variants = [
            [("Content-Type", "application/json")],
            [("Content-Type", "text/html; charset=shift_jis")],
            [("Content-Type", "text/html"), ("Content-Type", "text/plain")],
            [("Content-Type", "text/html"), ("Content-Encoding", "gzip")],
            [("Content-Type", "text/html"), ("Transfer-Encoding", "chunked")],
            [("Content-Type", "text/html"), ("Content-Length", "65537")],
            [("Content-Type", "text/html"), ("Content-Length", "0")],
            [
                ("Content-Type", "text/html"),
                ("Content-Length", "5"),
                ("Content-Length", "6"),
            ],
            [("Content-Type", "text/html"), ("X-Large", "x" * 8200)],
            [("Content-Type", "text/html")] + [("X-Header", "x")] * 33,
        ]
        for headers in variants:
            with self.subTest(headers=headers):
                self.routes["/contact/"] = (200, headers, HTML.encode())
                with (
                    patch.object(f.observer, "analyze") as parser,
                    self.assertRaises(t.TransportBlocked),
                ):
                    self.observe()
                parser.assert_not_called()

    def test_truncated_body_and_status_errors_do_not_parse_or_retry(self):
        for status, headers in [
            (200, [("Content-Type", "text/html"), ("Content-Length", "64000")]),
            (302, [("Location", "https://127.0.0.1/")]),
            (429, []),
            (503, []),
        ]:
            self.lab.events.clear()
            self.routes["/contact/"] = (status, headers, b"short")
            with (
                self.subTest(status=status),
                patch.object(f.observer, "analyze") as parser,
                self.assertRaises(t.TransportBlocked),
            ):
                self.observe()
            parser.assert_not_called()
            self.assertEqual(len(self.lab.events), 2)

    def test_unsafe_dns_never_dials(self):
        self.dns.return_value = ("8.8.8.8", "127.0.0.1")
        with self.assertRaises(t.TransportBlocked):
            self.observe()
        self.assertEqual(self.lab.dials, [])

    def test_rebinding_between_requests_stops_before_contact(self):
        self.dns.side_effect = [("8.8.8.8",), ("127.0.0.1",)]
        with self.assertRaises(t.TransportBlocked):
            self.observe()
        self.assertEqual([e[1] for e in self.lab.events], ["/robots.txt"])

    def test_tls_identity_mismatch_never_sends_http(self):
        other = TLSFixture(hostname="other.example")
        self.addCleanup(other.close)
        with (
            patch.object(t, "dial", side_effect=other.dial),
            self.assertRaises(t.TransportBlocked),
        ):
            f.observe_owned_page(context=other.context)
        self.assertEqual(other.events, [])

    def test_cancel_before_dns_and_after_robots(self):
        self.cancel.set()
        with self.assertRaises(t.TransportBlocked):
            self.observe()
        self.dns.assert_not_called()
        self.cancel.clear()
        self.cancel_after_robots = True
        with self.assertRaises(t.TransportBlocked):
            self.observe()
        self.assertEqual([e[1] for e in self.lab.events], ["/robots.txt"])

    def test_shared_deadline_stops_slow_robots_without_retry(self):
        self.delay = 0.2
        with self.assertRaises(t.TransportBlocked):
            self.observe(timeout=0.05)
        self.assertEqual(len(self.lab.dials), 1)
        self.assertEqual(len(self.lab.events), 1)

    def test_contact_uses_remaining_shared_budget_not_new_timeout(self):
        self.delay = 0.15
        with (
            patch.object(f, "get", wraps=f.get) as requests,
            self.assertRaises(t.TransportBlocked),
        ):
            self.observe(timeout=0.25)
        self.assertEqual(requests.call_count, 2)
        self.assertEqual(
            requests.call_args_list[0].args[2], requests.call_args_list[1].args[2]
        )
        self.assertEqual([e[1] for e in self.lab.events], ["/robots.txt", "/contact/"])

    def test_invalid_budgets_and_insecure_tls_stop_before_dns(self):
        for timeout in [0, -1, 31, float("nan"), float("inf")]:
            with self.subTest(timeout=timeout), self.assertRaises(t.TransportBlocked):
                self.observe(timeout=timeout)
        self.lab.context.check_hostname = False
        with self.assertRaises(t.TransportBlocked):
            self.observe()
        self.dns.assert_not_called()

    def test_prohibition_and_captcha_stay_blocked_or_human_required(self):
        for extra, decision in [
            ("<p>営業目的のお問い合わせはお断り</p>", "BLOCKED"),
            (
                "<script src='https://captcha.example/widget.js'></script>",
                "HUMAN_REQUIRED",
            ),
        ]:
            self.routes["/contact/"] = (
                200,
                [("Content-Type", "text/html")],
                (HTML + extra).encode(),
            )
            result = self.observe()
            self.assertEqual(result.observation.decision, decision)
            self.assertFalse(result.observation.eligible_for_approval)


if __name__ == "__main__":
    unittest.main()
