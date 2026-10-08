import unittest
from unittest.mock import Mock, patch

from readiness import PROBE, wait_for_database


class ReadinessTests(unittest.TestCase):
    def test_transient_readiness_retry_without_fixture_or_secrets(self):
        docker = Mock(side_effect=[RuntimeError("not ready"), ""])
        with patch("readiness.time.sleep") as sleep:
            wait_for_database(docker, "lab-wp", attempts=2)
        self.assertEqual(docker.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertIn("getenv('WORDPRESS_DB_PASSWORD')", PROBE)
        self.assertNotIn("print", PROBE)

    def test_timeout_stops_before_install(self):
        with (
            patch("readiness.time.sleep"),
            self.assertRaisesRegex(RuntimeError, "database did not become ready"),
        ):
            wait_for_database(
                Mock(side_effect=RuntimeError("not ready")), "lab-wp", attempts=2
            )
