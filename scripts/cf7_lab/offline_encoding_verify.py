"""Opt-in synthetic browser comparison. No DB, network, approval or form submission."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.cf7_candidate_contract import digest
from app.services.cf7_real_contract_preview import preview
from app.services.cf7_real_encoding import encode, summarize
from tests.test_cf7_real_contract_preview import fixture
from tests.test_cf7_real_encoding import mime_parts


def main():
    if os.environ.get("CF7_OFFLINE_ENCODING_TEST") != "1":
        raise RuntimeError("Explicit offline lab opt-in required")
    results = []
    for version in ("6.1.4", "6.2"):
        for choice in ("no_checkbox", "checked", "unchecked"):
            report, observation = fixture(version)
            report["snapshot"]["rows"][0]["values"] = ["日本語😀\nLF\rCR\r\nCRLF\n"]
            evidence = observation["cf7_static"]["contract_evidence"]
            if choice != "no_checkbox":
                evidence["controls"].append(
                    {
                        "name": "consent",
                        "kind": "checkbox",
                        "required": False,
                        "checkbox_value": "yes",
                    }
                )
                evidence["dom_order"].insert(2, "consent")
                report["snapshot"]["rows"].append(
                    {
                        "name": "consent",
                        "field_type": "checkbox",
                        "required": False,
                        "state": "HUMAN_SELECTION_RECORDED",
                        "values": ["yes"] if choice == "checked" else [],
                    }
                )
            report["snapshot"]["observation_hash"] = digest(observation)
            report["snapshot_hash"] = digest(report["snapshot"])
            current = preview(report, observation)
            encoded = encode(
                report, observation, expected_contract_hash=current["contract_hash"]
            )
            process = subprocess.run(
                ["node", str(Path(__file__).with_name("offline_encoding_browser.cjs"))],
                input=json.dumps(
                    {"evidence": evidence, "rows": report["snapshot"]["rows"]}
                ).encode(),
                capture_output=True,
                timeout=45,
                check=True,
                env={
                    key: os.environ[key]
                    for key in (
                        "SystemRoot",
                        "WINDIR",
                        "PATH",
                        "USERPROFILE",
                        "LOCALAPPDATA",
                        "CF7_OFFLINE_ENCODING_TEST",
                    )
                    if key in os.environ
                },
            )
            browser = json.loads(process.stdout)
            browser_parts = mime_parts(
                browser["content_type"], base64.b64decode(browser["body_base64"])
            )
            assert browser_parts == mime_parts(encoded.content_type, encoded.body)
            assert browser["external_requests"] == 0
            results.append(
                {
                    "version": version,
                    "choice": choice,
                    "parts": len(browser_parts),
                    "matched": True,
                    "wire_size": summarize(encoded)["wire_size"],
                }
            )
    result = {
        "definition": "synthetic-offline-browser-encoding-v1",
        "cases": results,
        "external_requests": 0,
        "email_sent": 0,
        "form_sent": 0,
        "approvals": 0,
        "scope": "Browser serialization only; not CF7 server acceptance",
    }
    destination = ROOT / "dist" / "cf7-offline-encoding-result.json"
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
