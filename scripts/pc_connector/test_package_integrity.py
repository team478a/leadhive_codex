"""Reject broken/traversing manifests before running archived browser input."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REQUIRED = (
    "runtime/node.exe",
    "runtime/chromium/chrome.exe",
    "frontend/node_modules/playwright/cli.js",
    "frontend/form-lab/offline-runner.config.ts",
    "scripts/pc_connector/Run-Offline-Input.ps1",
)


@pytest.mark.parametrize(
    "change", [None, "tampered", "missing", "traversal", "empty", "outbound"]
)
def test_package_integrity(tmp_path, change):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for package integrity verifier")
    files = {}
    for name in REQUIRED:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"fixture")
        files[name] = hashlib.sha256(b"fixture").hexdigest()
    verifier = tmp_path / "scripts/pc_connector/verify-runner.cjs"
    shutil.copyfile(Path(__file__).with_name("verify-runner.cjs"), verifier)
    if change == "tampered":
        (tmp_path / REQUIRED[0]).write_bytes(b"changed")
    elif change == "missing":
        (tmp_path / REQUIRED[0]).unlink()
    elif change == "traversal":
        files["../outside"] = hashlib.sha256(b"fixture").hexdigest()
    elif change == "empty":
        files = {}
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "definition": "pc-input-package-v1",
                "outbound": change == "outbound",
                "files": files,
            }
        )
    )
    run = subprocess.run(
        [node, str(verifier)], capture_output=True, check=False, timeout=30
    )
    assert run.returncode == (0 if change is None else 1)
