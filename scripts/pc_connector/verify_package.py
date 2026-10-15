"""Smoke test the extracted diagnostic ZIP without host Node/npm/Python on PATH."""

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    metadata = json.loads((ROOT / "dist/pc-input-latest.json").read_text())
    built_package = Path(metadata["package"])
    extracted = ROOT / "dist" / f"pc-acceptance-{uuid.uuid4().hex[:10]} 日本語 space"
    extracted.mkdir()
    with zipfile.ZipFile(metadata["zip"]) as archive:
        for name in archive.namelist():
            if (
                not name.startswith(built_package.name + "/")
                or ".." in name.split("/")
                or ":" in name
            ):
                raise RuntimeError("Invalid package archive path")
        archive.extractall(extracted)
    package = extracted / built_package.name
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "USERPROFILE",
            "APPDATA",
            "COMSPEC",
            "PATHEXT",
            "SYSTEMDRIVE",
            "PROGRAMDATA",
        }
    }
    env["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    env["NODE_OPTIONS"] = "--require=must-not-run"
    env["LEADHIVE_OFFLINE_REPORT_ORIGIN"] = "https://must-not-contact.example"
    env["LEADHIVE_OFFLINE_REPORT_LOOPBACK"] = "1"
    shell = (
        Path(os.environ["SYSTEMROOT"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    with tempfile.TemporaryDirectory(
        prefix="LeadHive 診断 ", ignore_cleanup_errors=True
    ) as private:
        task = Path(private) / "input.json"
        html = '<form><label>会社名<input name="company" required></label></form>'
        for permission, expected in [
            ("UNKNOWN", "OFFLINE_INPUT_VERIFIED"),
            ("PROHIBITED", "BLOCKED"),
        ]:
            task.write_text(
                json.dumps(
                    {
                        "html": html,
                        "expectedHtmlHash": hashlib.sha256(html.encode()).hexdigest(),
                        "sourceUrl": "https://synthetic.example/contact",
                        "permission": permission,
                        "values": {"company": "模擬会社"},
                        "choices": {},
                        "consents": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            run = subprocess.run(
                [
                    str(shell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(package / "scripts/pc_connector/Run-Offline-Input.ps1"),
                    "-InputFile",
                    str(task),
                ],
                cwd=private,
                env=env,
                timeout=90,
                capture_output=True,
                check=False,
            )
            if run.returncode:
                (ROOT / "dist/pc-input-smoke-output.log").write_bytes(
                    run.stdout + run.stderr
                )
                raise RuntimeError(
                    "Packaged diagnostic launcher failed (inspect private test output)"
                )
            reports = list(
                (package / "frontend/test-results/offline-input-runner").rglob(
                    "offline-input-result.json"
                )
            )
            if len(reports) != 1:
                raise RuntimeError("Exactly one diagnostic result is required")
            result = json.loads(reports[0].read_text())
            assert result["status"] == expected
            assert result["sent"] is False and result["approvalGranted"] is False
            assert result["liveFetchPerformed"] is False
            print(
                json.dumps(
                    {"permission": permission, "status": expected, "sent": False}
                )
            )
    # A modified packaged file must stop execution, not silently use a host runtime.
    notice = package / "README-FIRST.txt"
    original = notice.read_bytes()
    try:
        notice.write_bytes(original + b"changed")
        clean_env = {
            key: value for key, value in env.items() if not key.startswith("NODE_")
        }
        check = subprocess.run(
            [
                str(package / "runtime/node.exe"),
                str(package / "scripts/pc_connector/verify-runner.cjs"),
            ],
            env=clean_env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert check.returncode == 1
    finally:
        notice.write_bytes(original)
    print("Package smoke PASS: no host runtime, no external site access, no send")


if __name__ == "__main__":
    main()
