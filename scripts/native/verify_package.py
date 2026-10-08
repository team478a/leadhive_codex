"""Run the frozen package with no host Python, Node or Docker on PATH."""

import json
import os
import subprocess
import uuid
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    metadata = json.loads((root / "dist/native-latest.json").read_text())
    package = Path(metadata["package"])
    data = root / "dist" / f"native-acceptance-{uuid.uuid4().hex[:10]} 日本語 space"
    output = root / "dist/native-acceptance-result.json"
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
        }
    }
    env["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    # Malicious inherited flags/credentials must be discarded by the launcher.
    env.update(
        OUTBOUND_ENABLED="true",
        SMTP_PASSWORD="must-not-be-inherited",
        PYTHONPATH="invalid",
    )
    result = subprocess.run(
        [
            str(package / "LeadHiveEngine.exe"),
            "--data",
            str(data),
            "--smoke-report",
            str(output),
        ],
        cwd=Path(os.environ["TEMP"]),
        env=env,
        timeout=360,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
        capture_output=True,
    )
    if result.returncode or not output.exists():
        print(json.dumps({"native_exit_code": result.returncode}))
        if output.exists():
            print(output.read_text())
        for line in result.stderr.decode("utf-8", errors="replace").splitlines():
            try:
                diagnostic = json.loads(line)
            except ValueError:
                continue
            if isinstance(diagnostic, dict) and "error_type" in diagnostic:
                print(json.dumps(diagnostic))
        raise RuntimeError(
            "Native acceptance failed. Inspect private instance diagnostics."
        )
    report = json.loads(output.read_text())
    assert report["success"] and report["outbound"] == "false"
    assert report["admin_login"] and report["session"]
    assert "stop_error_type" not in report
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
