"""Gateway boundary tests use a fake Docker response; no container is started."""

import http.client
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
from gateway import gateway, permitted_target

CONTAINER = "leadhive-cf7-lab-0123456789ab-wp"
ROUTE = "/wp-json/contact-form-7/v1/contact-forms/7/feedback"


class GatewayTests(unittest.TestCase):
    def test_targets_are_local_and_post_is_only_feedback(self):
        for path in (
            ROUTE,
            ROUTE.replace("/wp-json/", "/?rest_route=/"),
            ROUTE.replace("/wp-json/", "/index.php?rest_route=/"),
        ):
            self.assertTrue(permitted_target("POST", path))
        for path in (
            "https://evil.example/",
            "//evil.example/",
            "/wp-admin/",
            ROUTE + "?redirect=evil",
            ROUTE + "\r\nHost: evil",
            "/?rest_route=https://evil.example/",
            ROUTE + "#fragment",
        ):
            with self.subTest(path=path):
                self.assertFalse(permitted_target("POST", path))
        self.assertFalse(permitted_target("GET", "https://evil.example/"))

    def test_unrelated_container_is_never_used(self):
        with self.assertRaises(ValueError), gateway("leadhive-location-preview-api"):
            self.fail("Gateway must not start")

    def test_wire_preserved_but_credentials_not_forwarded(self):
        fake = subprocess.CompletedProcess(
            [],
            0,
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Set-Cookie: secret=value\r\nContent-Length: 2\r\n\r\n{}",
            b"",
        )
        with (
            patch("gateway.subprocess.run", return_value=fake) as relay,
            gateway(CONTAINER) as origin,
        ):
            with httpx.Client(trust_env=False, timeout=5) as client:
                response = client.post(
                    origin + ROUTE,
                    content=b"lab-body",
                    headers={
                        "Cookie": "human=secret",
                        "Authorization": "Bearer secret",
                        "X-API-Key": "secret",
                        "Host": "evil.example",
                        "Content-Type": "multipart/form-data; boundary=test",
                    },
                )
            self.assertEqual(response.json(), {})
            self.assertNotIn("set-cookie", response.headers)
            relay.assert_called_once()
            args, kwargs = relay.call_args
            self.assertEqual(
                args[0],
                ["docker", "exec", "-i", CONTAINER, "php", "/opt/cf7-lab/relay.php"],
            )
            wire = kwargs["input"]
            self.assertIn(b"Host: 127.0.0.1:", wire)
            self.assertTrue(wire.endswith(b"lab-body"))
            self.assertNotIn(b"secret", wire)
            self.assertNotIn(b"evil.example", wire)

    def test_invalid_post_and_oversize_do_not_reach_docker(self):
        with patch("gateway.subprocess.run") as relay, gateway(CONTAINER) as origin:
            with httpx.Client(trust_env=False, timeout=5) as client:
                self.assertEqual(
                    client.post(origin + "/wp-admin/", content=b"").status_code, 403
                )
            # Header admission rejects before reading a body. Sending a full
            # rejected body races socket close on Windows and can report RST
            # instead of the already-written 413. No retry or limit relaxation.
            parsed = urlsplit(origin)
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=5
            )
            try:
                connection.putrequest("POST", ROUTE)
                connection.putheader("Content-Length", "64001")
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, 413)
                response.read()
            finally:
                connection.close()
            relay.assert_not_called()

    def test_relay_failure_has_no_automatic_retry_or_error_leak(self):
        fake = subprocess.CompletedProcess([], 1, b"", b"private diagnostic")
        with (
            patch("gateway.subprocess.run", return_value=fake) as relay,
            gateway(CONTAINER) as origin,
        ):
            with httpx.Client(trust_env=False, timeout=5) as client:
                response = client.post(origin + ROUTE, content=b"lab")
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("private diagnostic", response.text)
            relay.assert_called_once()


if __name__ == "__main__":
    unittest.main()
