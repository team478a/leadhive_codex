"""All network traffic is redirected by test-only patching to a loopback TLS server."""

import datetime
import os
import socket
import ssl
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpcore
import transport as t
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class TLSFixture:
    def __init__(self, hostname="managed.example", expired=False):
        self.temp = tempfile.TemporaryDirectory(prefix="leadhive-tls-")
        self.events, self.sni = [], []
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=2))
            .not_valid_after(now + datetime.timedelta(days=-1 if expired else 1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256())
        )
        certpath, keypath = (
            Path(self.temp.name) / "cert.pem",
            Path(self.temp.name) / "key.pem",
        )
        certpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        keypath.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        events = self.events

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.reply()

            def do_POST(self):
                self.reply()

            def reply(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                events.append((self.command, self.path, dict(self.headers), body))
                if self.path == "/slow":
                    time.sleep(0.3)
                self.send_response(
                    int(self.path.removeprefix("/redirect"))
                    if self.path.startswith("/redirect")
                    else 200
                )
                self.send_header("Location", "https://127.0.0.1/private")
                self.send_header("Set-Cookie", "secret=not-forwarded")
                if self.path == "/gzip":
                    self.send_header("Content-Encoding", "gzip")
                data = b"x" * 100 if self.path == "/large" else b"managed receipt"
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certpath, keypath)
        context.set_servername_callback(lambda sock, name, ctx: self.sni.append(name))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.context = ssl.create_default_context(cafile=str(certpath))
        self.dials = []

    def dial(self, address, timeout):
        self.dials.append(address)
        return socket.create_connection(self.server.server_address, timeout=timeout)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"PINNED_TLS_LAB": "1"})
        self.env.start()
        self.lab = TLSFixture()
        self.addCleanup(self.lab.close)
        self.addCleanup(self.env.stop)

    def exchange(self, path="/receipt", **kwargs):
        with (
            patch.object(t, "resolve", return_value=("8.8.8.8",)) as dns,
            patch.object(t, "dial", side_effect=self.lab.dial),
        ):
            result = t.exchange(
                "https://managed.example" + path,
                context=kwargs.pop("context", self.lab.context),
                **kwargs,
            )
        self.assertEqual(dns.call_count, 1)
        return result

    def test_verified_tls_original_sni_host_and_exact_payload(self):
        result = self.exchange(method="POST", body=b"fake payload")
        self.assertEqual(
            (result.status, result.body, result.pinned_ip),
            (200, b"managed receipt", "8.8.8.8"),
        )
        self.assertEqual(self.lab.sni, ["managed.example"])
        self.assertEqual(self.lab.dials, ["8.8.8.8"])
        self.assertEqual(self.lab.events[0][2]["Host"], "managed.example")
        self.assertEqual(self.lab.events[0][3], b"fake payload")

    def test_rebinding_no_second_resolution_or_address_fallback(self):
        with (
            patch.object(
                t, "resolve", side_effect=[("8.8.8.8", "1.1.1.1"), ("127.0.0.1",)]
            ) as dns,
            patch.object(t, "dial", side_effect=self.lab.dial),
        ):
            t.exchange("https://managed.example/", context=self.lab.context)
        self.assertEqual(dns.call_count, 1)
        self.assertEqual(self.lab.dials, ["8.8.8.8"])

    def test_mixed_and_unsafe_dns_never_connect(self):
        for addresses in [
            ("8.8.8.8", "127.0.0.1"),
            ("169.254.169.254",),
            ("10.0.0.1",),
            ("::1",),
            ("ff02::1",),
            ("::ffff:8.8.8.8",),
            ("2002:0808:0808::1",),
            ("64:ff9b::7f00:1",),
            (),
            ("bad",),
        ]:
            with (
                self.subTest(addresses=addresses),
                patch.object(t, "resolve", return_value=addresses),
                patch.object(t, "dial") as dial,
            ):
                with self.assertRaises(t.TransportBlocked):
                    t.exchange("https://managed.example/")
                dial.assert_not_called()

    def test_bad_urls_never_resolve(self):
        for url in [
            "http://managed.example/",
            "https://u:p@managed.example/",
            "https://managed.example:444/",
            "https://127.0.0.1/",
            "https://[::1]/",
            "https://managed.example/#fragment",
            "https://managed.example\\@evil.example/",
            "https://managed.example./",
            "https://managed.example/\r\nX:evil",
            "https://-bad.example/",
        ]:
            with self.subTest(url=url), patch.object(t, "resolve") as dns:
                with self.assertRaises(t.TransportBlocked):
                    t.exchange(url)
                dns.assert_not_called()

    def test_opt_in_precedes_all_io(self):
        with (
            patch.dict(os.environ, {"PINNED_TLS_LAB": "0"}),
            patch.object(t, "resolve") as dns,
        ):
            with self.assertRaises(t.TransportBlocked):
                t.exchange("https://managed.example/")
            dns.assert_not_called()

    def test_untrusted_certificate_no_http(self):
        with self.assertRaises(httpcore.ConnectError):
            self.exchange(
                context=httpcore.default_ssl_context(), method="POST", body=b"fake"
            )
        self.assertEqual(self.lab.events, [])
        self.assertEqual(len(self.lab.dials), 1)

    def test_wrong_hostname_and_expired_cert_no_http(self):
        for name, expired in [("other.example", False), ("managed.example", True)]:
            fixture = TLSFixture(name, expired)
            try:
                with (
                    patch.object(t, "resolve", return_value=("8.8.8.8",)),
                    patch.object(t, "dial", side_effect=fixture.dial),
                    self.assertRaises(httpcore.ConnectError),
                ):
                    t.exchange(
                        "https://managed.example/",
                        context=fixture.context,
                        method="POST",
                        body=b"fake",
                    )
                self.assertEqual(fixture.events, [])
                self.assertEqual(len(fixture.dials), 1)
            finally:
                fixture.close()

    def test_verification_cannot_be_disabled(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with patch.object(t, "resolve") as dns:
            with self.assertRaises(t.TransportBlocked):
                t.exchange("https://managed.example/", context=context)
            dns.assert_not_called()

    def test_redirect_post_not_followed(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status), self.assertRaises(t.TransportBlocked):
                self.exchange(f"/redirect{status}", method="POST", body=b"fake")
        self.assertEqual(len(self.lab.events), 5)
        self.assertEqual(len(self.lab.dials), 5)

    def test_environment_proxy_trust_and_cookies_not_inherited(self):
        with patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "ALL_PROXY": "http://127.0.0.1:1",
                "SSL_CERT_FILE": "missing-invalid-ca.pem",
            },
        ):
            self.exchange()
            self.exchange()
        for event in self.lab.events:
            self.assertNotIn("Cookie", event[2])
            self.assertNotIn("Authorization", event[2])
            self.assertNotIn("Proxy-Authorization", event[2])

    def test_connect_failure_no_retry(self):
        with (
            patch.object(t, "resolve", return_value=("8.8.8.8", "1.1.1.1")),
            patch.object(
                t, "dial", side_effect=httpcore.ConnectError("fixture")
            ) as dial,
        ):
            with self.assertRaises(httpcore.ConnectError):
                t.exchange("https://managed.example/")
            self.assertEqual(dial.call_count, 1)

    def test_compressed_and_oversized_response_stop_no_retry(self):
        for path, kwargs in [("/gzip", {}), ("/large", {"limit": 10})]:
            with self.subTest(path=path), self.assertRaises(t.TransportBlocked):
                self.exchange(path, **kwargs)
        self.assertEqual(len(self.lab.events), 2)

    def test_slow_response_stops_no_retry(self):
        with self.assertRaises(httpcore.ReadTimeout):
            self.exchange("/slow", timeout=0.15)
        self.assertEqual(len(self.lab.events), 1)
        self.assertEqual(len(self.lab.dials), 1)

    def test_numeric_dial_has_no_getaddrinfo(self):
        with (
            patch.object(socket, "socket") as factory,
            patch.object(socket, "getaddrinfo") as dns,
        ):
            t.dial("8.8.8.8", 1)
            factory.return_value.connect.assert_called_once_with(("8.8.8.8", 443))
            dns.assert_not_called()

    def test_default_trust_does_not_consult_environment(self):
        with patch.dict(
            os.environ, {"SSL_CERT_FILE": "missing.pem", "SSL_CERT_DIR": "missing"}
        ):
            context = httpcore.default_ssl_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)

    def test_dns_failure_and_deadline_exhaustion_never_connect(self):
        with (
            patch.object(
                socket, "getaddrinfo", side_effect=socket.gaierror("secret failure")
            ),
            self.assertRaisesRegex(t.TransportBlocked, "^DNS resolution failed$"),
        ):
            t.resolve("managed.example")

        def slow_dns(host):
            time.sleep(0.03)
            return ("8.8.8.8",)

        with (
            patch.object(t, "resolve", side_effect=slow_dns),
            patch.object(t, "dial") as dial,
        ):
            with self.assertRaises(httpcore.ConnectTimeout):
                t.exchange("https://managed.example/", timeout=0.01)
            dial.assert_not_called()

    def test_backend_connection_identity_and_single_use(self):
        backend = t.PinnedBackend("managed.example", ("8.8.8.8",), time.monotonic() + 5)
        with patch.object(t, "dial") as dial:
            for host, port in [("other.example", 443), ("managed.example", 80)]:
                with self.assertRaises(t.TransportBlocked):
                    backend.connect_tcp(host, port)
            dial.assert_not_called()
            stream = backend.connect_tcp("managed.example", 443)
            stream.close()
            with self.assertRaises(t.TransportBlocked):
                backend.connect_tcp("managed.example", 443)
            self.assertEqual(dial.call_count, 1)


if __name__ == "__main__":
    unittest.main()
