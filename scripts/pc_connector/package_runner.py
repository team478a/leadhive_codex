"""Build a Windows x64 diagnostic-only ZIP from a committed source allowlist."""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    "frontend/form-lab/offline-input.ts",
    "frontend/form-lab/offline-runner.case.ts",
    "frontend/form-lab/offline-runner.config.ts",
    "frontend/form-lab/report-transfer.ts",
    "frontend/src/offlineHandoffContract.ts",
    "scripts/pc_connector/Run-Offline-Input.cmd",
    "scripts/pc_connector/Run-Offline-Input.ps1",
    "scripts/pc_connector/verify-runner.cjs",
    "docs/PC_INPUT_RUNNER_QUICKSTART.txt",
)
MODULES = ("@playwright/test", "playwright", "playwright-core")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_tree(source, target):
    if source.is_symlink() or any(p.is_symlink() for p in source.rglob("*")):
        raise RuntimeError("Runtime symlinks are not allowed")
    shutil.copytree(source, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().upper() not in {
        "AMD64",
        "X86_64",
    }:
        raise RuntimeError("Build on Windows x64")
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if dirty.strip() and not args.development:
        raise RuntimeError("Commit and review changes before release packaging")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Build machine requires Node.js")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        raise RuntimeError("Node.js 22 or later is required")
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    for module in MODULES:
        installed = json.loads(
            (ROOT / "frontend/node_modules" / module / "package.json").read_text()
        )
        if (
            installed["version"]
            != lock["packages"][f"node_modules/{module}"]["version"]
        ):
            raise RuntimeError("Run npm ci on the build machine")
    browser = Path(
        subprocess.check_output(
            [
                node,
                "-e",
                "console.log(require('./node_modules/playwright').chromium.executablePath())",
            ],
            cwd=ROOT / "frontend",
            text=True,
        ).strip()
    )
    if browser.name != "chrome.exe" or not browser.is_file():
        raise RuntimeError("Install Playwright Chromium on the build machine")
    output = ROOT / "dist" / f"pc-input-{commit[:12]}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True)
    for relative in SOURCES:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.development:
            shutil.copyfile(ROOT / relative, target)
        else:
            target.write_bytes(
                subprocess.check_output(
                    ["git", "show", f"{commit}:{relative}"], cwd=ROOT
                )
            )
    shutil.copyfile(
        output / "scripts/pc_connector/Run-Offline-Input.cmd", output / "Start.cmd"
    )
    # Root entry points need the repository-shaped script directory.
    (output / "Start.cmd").write_bytes(
        b'@echo off\r\ncall "%~dp0scripts\\pc_connector\\Run-Offline-Input.cmd"\r\n'
    )
    shutil.copyfile(
        output / "docs/PC_INPUT_RUNNER_QUICKSTART.txt", output / "README-FIRST.txt"
    )
    (output / "frontend/package.json").write_text(
        '{"private":true,"type":"module"}', encoding="utf-8"
    )
    for module in MODULES:
        copy_tree(
            ROOT / "frontend/node_modules" / module,
            output / "frontend/node_modules" / module,
        )
    (output / "runtime").mkdir()
    runtime_lock = json.loads(
        (ROOT / "scripts/pc_connector/runtime-lock.json").read_text()
    )
    cache = ROOT / "dist" / f"node-{runtime_lock['node_sha256']}.zip"
    if not cache.exists():
        with urllib.request.urlopen(runtime_lock["node_url"], timeout=60) as response:
            data = response.read(150_000_001)
        if len(data) > 150_000_000:
            raise RuntimeError("Runtime download exceeds budget")
        cache.write_bytes(data)
    if digest(cache) != runtime_lock["node_sha256"]:
        raise RuntimeError("Node runtime SHA-256 mismatch")
    prefix = f"node-{runtime_lock['node_version']}-win-x64/"
    with zipfile.ZipFile(cache) as archive:
        (output / "runtime/node.exe").write_bytes(archive.read(prefix + "node.exe"))
        (output / "runtime/NODE-LICENSE.txt").write_bytes(
            archive.read(prefix + "LICENSE")
        )
    copy_tree(browser.parent, output / "runtime/chromium")
    files = {
        p.relative_to(output).as_posix(): digest(p)
        for p in output.rglob("*")
        if p.is_file()
    }
    manifest = {
        "definition": "pc-input-package-v1",
        "commit": commit,
        "development": args.development,
        "node_version": runtime_lock["node_version"],
        "playwright_version": lock["packages"]["node_modules/playwright"]["version"],
        "architecture": "Windows x64",
        "outbound": False,
        "files": files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    zip_path = output.with_suffix(".zip")
    with zipfile.ZipFile(
        zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1
    ) as archive:
        for path in output.rglob("*"):
            if path.is_file():
                archive.write(
                    path, f"{output.name}/{path.relative_to(output).as_posix()}"
                )
    zip_path.with_suffix(".zip.sha256").write_text(digest(zip_path), encoding="ascii")
    (ROOT / "dist/pc-input-latest.json").write_text(
        json.dumps({"package": str(output), "zip": str(zip_path)}), encoding="utf-8"
    )
    print(
        json.dumps(
            {"commit": commit, "development": args.development, "zip": str(zip_path)}
        )
    )


if __name__ == "__main__":
    main()
