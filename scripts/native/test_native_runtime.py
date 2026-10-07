import json
import os
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import native_runtime as native
from packaging_resources import utf8_manifest


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
        for key in ("SMTP_PASSWORD", "OPENAI_API_KEY"):
            self.assertEqual(env[key], "")
        self.assertNotIn("PYTHONPATH", env)
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

    def test_postgres_daemon_uses_regular_log_not_pipe(self):
        exe = self.root / "postgresql/bin/pg_ctl.exe"
        exe.parent.mkdir(parents=True)
        exe.touch()
        with (
            patch.object(native, "bundle", return_value=self.root),
            patch.object(native.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            native.command(self.root, "pg_ctl.exe", "start")
            self.assertNotEqual(run.call_args.kwargs["stdout"], native.subprocess.PIPE)

    @unittest.skipUnless(os.name == "nt", "Windows filesystem codepage")
    def test_postgres_path_decoded_before_utf8_loader(self):
        target = self.root / "日本語"
        db = MagicMock()
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.execute.return_value.fetchone.return_value = (
            str(target).encode("cp932"),
        )
        with patch("ctypes.windll.kernel32.GetACP", return_value=932):
            self.assertEqual(native.cluster_directory(db), target.resolve())

    def test_utf8_manifest_preserves_privileges_and_is_idempotent(self):
        original = b'<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0"><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly>'
        manifest = utf8_manifest(original)
        tree = ET.fromstring(manifest)
        level = tree.find(
            ".//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel"
        )
        self.assertEqual(level.get("level"), "asInvoker")
        self.assertEqual(manifest, utf8_manifest(manifest))
        self.assertEqual(
            len(
                tree.findall(
                    ".//{http://schemas.microsoft.com/SMI/2019/WindowsSettings}activeCodePage"
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
