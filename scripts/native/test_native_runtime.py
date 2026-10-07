import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import native_runtime as native


class NativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = {
            "format": "leadhive-native-v1",
            "root": str(self.root),
            "id": str(uuid.uuid4()),
            "phase": "READY",
            "db_port": 25432,
            "web_port": 18990,
        }
        native.save_state(self.root, self.state)

    def test_moved_instance_rejected(self):
        self.state["root"] = str(self.root / "another-pc")
        native.save_state(self.root, self.state)
        with self.assertRaises(ValueError):
            native.read_state(self.root)

    def test_incomplete_installation_cannot_start(self):
        self.state["phase"] = "INSTALLING"
        native.save_state(self.root, self.state)
        with self.assertRaises(RuntimeError):
            native.read_state(self.root)

    def test_invalid_ports_rejected(self):
        for value in (True, 1, 70000, "18990"):
            self.state["web_port"] = value
            native.save_state(self.root, self.state)
            with self.assertRaises(ValueError):
                native.read_state(self.root)

    def test_host_credentials_and_send_flags_not_inherited(self):
        with (
            patch.dict(
                os.environ,
                {
                    "SMTP_PASSWORD": "host-secret",
                    "OPENAI_API_KEY": "host-key",
                    "OUTBOUND_ENABLED": "true",
                    "PYTHONPATH": "malicious",
                },
            ),
            patch.object(
                native,
                "secret_values",
                return_value={"database_password": "abc123", "encryption_key": "test"},
            ),
        ):
            env = native.environment(self.root)
        for key in ("SMTP_PASSWORD", "OPENAI_API_KEY", "PYTHONPATH"):
            self.assertNotIn(key, env)
        for key in native.OFF_FLAGS:
            self.assertEqual(env[key], "false")
        self.assertIn("127.0.0.1:25432/leadhive_native", env["DATABASE_URL"])

    def test_nonempty_directory_never_adopted(self):
        with self.assertRaises(RuntimeError):
            native.install(self.root, "admin@example.com", "a-valid-password-123")
        self.assertEqual(
            json.loads((self.root / "instance.json").read_text()), self.state
        )

    def test_drive_root_rejected(self):
        with self.assertRaises(ValueError):
            native.checked_root(Path(self.root.anchor))


if __name__ == "__main__":
    unittest.main()
