import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import dns_worker
import httpcore
import resolver as r
import transport as t


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"PINNED_TLS_LAB": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="leadhive-dns-")
        self.addCleanup(self.temp.cleanup)
        self.marker = Path(self.temp.name) / "ready.txt"
        self.children = []
        self.peak = 0
        self.lock = threading.Lock()
        original = subprocess.Popen
        self.popen_class = original

        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            with self.lock:
                self.children.append(child)
                self.peak = max(self.peak, sum(p.poll() is None for p in self.children))
            return child

        self.command = patch.object(
            r,
            "worker_command",
            side_effect=lambda host: [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("dns_fixture.py")),
                host,
                str(self.marker),
            ],
        )
        self.spawn = patch.object(r.subprocess, "Popen", side_effect=spawn)
        self.command.start()
        self.spawn.start()
        self.addCleanup(self.command.stop)
        self.addCleanup(self.spawn.stop)
        self.addCleanup(self.confirm_cleanup)

    def confirm_cleanup(self):
        for child in self.children:
            self.assertIsNotNone(child.poll(), "DNS child survived")
            self.assertTrue(child.stdout.closed)

    def test_real_child_success_codec_and_cleanup(self):
        self.assertEqual(
            r.isolated_resolve("success.example"), ("8.8.8.8", "2606:4700:4700::1111")
        )
        self.assertEqual(len(self.children), 1)

    def test_actual_hang_killed_and_reaped_no_late_result(self):
        started = time.monotonic()
        with self.assertRaises(r.ResolutionTimeout):
            r.isolated_resolve("hang.example", timeout=1)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(self.marker.read_text(encoding="ascii"), "ready")
        self.assertIsNotNone(self.children[0].poll())
        self.assertEqual(
            r.isolated_resolve("success.example"), ("8.8.8.8", "2606:4700:4700::1111")
        )

    def test_repeated_timeouts_leave_no_children_or_lost_slots(self):
        for _ in range(3):
            with self.assertRaises(r.ResolutionTimeout):
                r.isolated_resolve("hang.example", timeout=0.4)
            self.assertIsNotNone(self.children[-1].poll())
        self.assertEqual(len(r.isolated_resolve("success.example")), 2)

    def test_child_error_and_malformed_result_are_sanitized(self):
        for host in ("crash.example", "invalid.example"):
            with (
                self.subTest(host=host),
                self.assertRaises(r.ResolutionFailure) as error,
            ):
                r.isolated_resolve(host)
            self.assertNotIn("secret", str(error.exception))

    def test_credentials_and_python_proxy_env_not_inherited(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "fake-secret",
                "OPENAI_API_KEY": "fake",
                "SMTP_PASSWORD": "fake",
                "HTTPS_PROXY": "fake",
                "PYTHONPATH": "fake",
                "PYTHONSTARTUP": "fake",
            },
        ):
            self.assertEqual(len(r.isolated_resolve("env.example")), 2)

    def test_admission_timeout_does_not_spawn(self):
        gate = threading.BoundedSemaphore(1)
        gate.acquire()
        with patch.object(r, "SLOTS", gate), self.assertRaises(r.ResolutionTimeout):
            r.isolated_resolve("success.example", timeout=0.05)
        self.assertEqual(self.children, [])
        gate.release()

    def test_cancellation_kills_owned_process(self):
        with (
            patch.object(
                self.popen_class, "communicate", side_effect=KeyboardInterrupt
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            r.isolated_resolve("hang.example")
        self.assertEqual(len(self.children), 1)

    def test_no_optin_or_bad_input_never_spawns(self):
        with (
            patch.dict(os.environ, {"PINNED_TLS_LAB": "0"}),
            self.assertRaises(r.ResolutionFailure),
        ):
            r.isolated_resolve("success.example")
        for host, timeout in [
            ("bad; command", 1),
            ("-bad.example", 1),
            ("success.example", 0),
            ("success.example", float("nan")),
            ("success.example", 31),
        ]:
            with (
                self.subTest(host=host, timeout=timeout),
                self.assertRaises(r.ResolutionFailure),
            ):
                r.isolated_resolve(host, timeout)
        self.assertEqual(self.children, [])

    def test_transport_timeout_never_dials_or_posts(self):
        with patch.object(t, "dial") as dial:
            with self.assertRaises(httpcore.ConnectTimeout):
                t.exchange(
                    "https://hang.example/", method="POST", body=b"fake", timeout=1
                )
            dial.assert_not_called()
        self.assertEqual(self.marker.read_text(encoding="ascii"), "ready")

    def test_unsafe_child_result_still_blocked_in_parent(self):
        with (
            patch.object(t, "isolated_resolve", return_value=("8.8.8.8", "127.0.0.1")),
            patch.object(t, "dial") as dial,
        ):
            with self.assertRaises(t.TransportBlocked):
                t.exchange("https://success.example/", method="POST", body=b"fake")
            dial.assert_not_called()

    def test_worker_codec_with_mocked_os_dns_no_external_lookup(self):
        with patch.object(
            socket,
            "getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
            ],
        ) as dns:
            self.assertEqual(
                r.decode(dns_worker.lookup("managed.example")), ("8.8.8.8",)
            )
            dns.assert_called_once_with("managed.example", 443, type=socket.SOCK_STREAM)

    def test_parallel_hangs_respect_admission_and_all_children_end(self):
        outcomes = []

        def attempt():
            try:
                r.isolated_resolve("hang.example", timeout=0.6)
            except r.ResolutionTimeout:
                outcomes.append("timeout")
            except r.ResolutionFailure as error:
                outcomes.append(type(error).__name__)

        threads = [threading.Thread(target=attempt) for _ in range(4)]
        with patch.object(r, "SLOTS", threading.BoundedSemaphore(2)):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, ["timeout"] * 4)
        self.assertLessEqual(self.peak, 2)
        self.assertGreaterEqual(self.peak, 1)

    def test_bounded_strict_protocol(self):
        for value in [
            b"",
            b"x" * 8193,
            b"not json",
            b'{"version":1,"version":1,"addresses":["8.8.8.8"]}',
            json.dumps({"version": True, "addresses": ["8.8.8.8"]}).encode(),
            json.dumps({"version": 1, "addresses": []}).encode(),
            json.dumps({"version": 1, "addresses": ["fe80::1%2"]}).encode(),
            json.dumps({"version": 1, "addresses": ["8.8.8.8"] * 65}).encode(),
        ]:
            with self.subTest(value=value[:50]), self.assertRaises(r.ResolutionFailure):
                r.decode(value)

    def test_worker_overflow_and_invalid_os_address_rejected(self):
        valid = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        for answers in [
            [],
            [valid] * 65,
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("x" * 65, 443))],
        ]:
            with (
                patch.object(socket, "getaddrinfo", return_value=answers),
                self.assertRaises(ValueError),
            ):
                dns_worker.lookup("managed.example")

    def test_real_worker_isolated_entrypoint_has_no_application_imports(self):
        with (
            patch.object(
                r,
                "worker_command",
                return_value=[
                    sys.executable,
                    "-I",
                    str(Path(__file__).with_name("dns_worker.py")),
                ],
            ),
            self.assertRaisesRegex(r.ResolutionFailure, "^DNS resolution failed$"),
        ):
            r.isolated_resolve("managed.example")
        self.assertEqual(len(self.children), 1)

    def test_failed_spawn_and_unconfirmed_cleanup_quarantine(self):
        with (
            patch.object(r.subprocess, "Popen", side_effect=OSError("fake-secret")),
            self.assertRaisesRegex(r.ResolutionFailure, "^DNS process failed$"),
        ):
            r.isolated_resolve("success.example")
        # Failure injection is fake; no real unkillable process is created.
        fake = unittest.mock.Mock()
        fake.communicate.side_effect = subprocess.TimeoutExpired("fixture", 1)
        fake.poll.return_value = None
        fake.wait.side_effect = subprocess.TimeoutExpired("fixture", 1)
        fault = threading.Event()
        with (
            patch.object(r, "FAULT", fault),
            patch.object(r, "FAILED_CHILDREN", []),
            patch.object(r.subprocess, "Popen", return_value=fake),
        ):
            with self.assertRaises(r.ResolutionCleanupFailure):
                r.isolated_resolve("success.example")
            self.assertTrue(fault.is_set())
            self.assertEqual(r.FAILED_CHILDREN, [fake])
            fake.stdout.close.assert_not_called()
            with self.assertRaisesRegex(r.ResolutionCleanupFailure, "quarantined"):
                r.isolated_resolve("success.example")


if __name__ == "__main__":
    unittest.main()
