"""Build-only dependencies; no downloads, Docker or package installs on the target PC."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/native"))


def run(*args, cwd=ROOT):
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--development",
        action="store_true",
        help="Uncommitted prototype only; not a release",
    )
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().upper() not in {
        "AMD64",
        "X86_64",
    }:
        raise RuntimeError("Build on Windows x64")
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if dirty and not args.development:
        raise RuntimeError("Release requires a clean committed checkout")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    stage = ROOT / "dist" / f"native-build-{uuid.uuid4().hex[:10]}"
    stage.mkdir(parents=True)
    lock = json.loads((ROOT / "scripts/native/runtime-lock.json").read_text())
    pg = lock["postgresql"]
    cache = ROOT / "dist/native-cache" / pg["url"].rsplit("/", 1)[1]
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        temporary = stage / "postgresql-download.zip"
        with (
            urllib.request.urlopen(pg["url"], timeout=120) as response,
            temporary.open("wb") as target,
        ):
            shutil.copyfileobj(response, target)
        if digest(temporary) != pg["sha256"]:
            raise RuntimeError("PostgreSQL download hash mismatch")
        temporary.replace(cache)
    if cache.stat().st_size != pg["bytes"] or digest(cache) != pg["sha256"]:
        raise RuntimeError("PostgreSQL cache hash mismatch")
    run("npm.cmd", "run", "build", cwd=ROOT / "frontend")
    name = f"LeadHive-Windows-Native-{commit[:8]}" + ("-DEVELOPMENT" if dirty else "")
    spec = stage / "native.spec"
    spec.write_text(
        f"""import sys
sys.path.insert(0, {str(ROOT / "scripts/native")!r})
from packaging_resources import utf8_manifest
from PyInstaller.utils.win32.winmanifest import create_application_manifest
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
a = Analysis([{str(ROOT / "scripts/native/entry.py")!r}],
    pathex={[str(ROOT / "backend"), str(ROOT / "scripts/native")]!r},
    binaries=[], datas=[({str(ROOT / "backend/migrations")!r}, 'migrations'),
        ({str(ROOT / "frontend/dist")!r}, 'web')] + collect_data_files('app'),
    hiddenimports=collect_submodules('app') + collect_submodules('uvicorn') +
        collect_submodules('sqlalchemy.dialects.postgresql') + ['psycopg', 'psycopg_binary'],
    hookspath=[], runtime_hooks=[], excludes=['pytest', 'ruff', 'mypy'], noarchive=False)
pyz = PYZ(a.pure)
manifest = utf8_manifest(create_application_manifest())
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LeadHive', console=False, manifest=manifest)
engine = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LeadHiveEngine', console=True, manifest=manifest)
bundle = COLLECT(gui, engine, a.binaries, a.datas, strip=False, upx=False, name={name!r})
""",
        encoding="utf-8",
    )
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        stage / "output",
        "--workpath",
        stage / "work",
        spec,
    )
    package = stage / "output" / name
    pgroot = package / "postgresql"
    pgroot.mkdir()
    with zipfile.ZipFile(cache) as archive:
        for item in archive.infolist():
            path = Path(item.filename)
            # Keep server runtime and ALL top-level licenses; omit optional pgAdmin/StackBuilder.
            if not path.parts or path.parts[0] != "pgsql" or len(path.parts) < 2:
                continue
            if path.parts[1] in {"pgAdmin 4", "StackBuilder"}:
                continue
            target = (pgroot / Path(*path.parts[1:])).resolve()
            if not target.is_relative_to(pgroot.resolve()):
                raise RuntimeError("Unsafe archive entry")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
    from packaging_resources import configure_postgres

    adjustments = configure_postgres(pgroot / "bin")
    shutil.copy(ROOT / "scripts/native/README-FIRST.txt", package / "README-FIRST.txt")
    notices = package / "licenses/python-packages"
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or []:
            if any(
                "license" in part.lower() or "copying" in part.lower()
                for part in file.parts
            ):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = notices / distribution.metadata["Name"] / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    shutil.copy(
        ROOT / "backend/requirements.lock",
        package / "licenses/backend-requirements.lock",
    )
    manifest = {
        "format": "leadhive-native-package-v1",
        "commit": commit,
        "development": bool(dirty),
        "runtime": lock,
        "runtime_adjustments": adjustments,
        "outbound": False,
        "worker_default": False,
        "files": {
            str(p.relative_to(package)): digest(p)
            for p in package.rglob("*")
            if p.is_file()
        },
    }
    (package / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    zip_path = ROOT / "dist" / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in package.rglob("*"):
            if path.is_file():
                archive.write(path, Path(name) / path.relative_to(package))
    zip_path.with_suffix(".zip.sha256").write_text(
        f"{digest(zip_path)}  {zip_path.name}\n"
    )
    (ROOT / "dist/native-latest.json").write_text(
        json.dumps({"package": str(package), "zip": str(zip_path), "commit": commit})
    )
    print(
        json.dumps(
            {"package": str(package), "zip": str(zip_path), "sha256": digest(zip_path)}
        )
    )


if __name__ == "__main__":
    main()
