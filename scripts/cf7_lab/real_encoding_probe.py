"""Fixed loopback reception of the real-preview encoder, never production dispatch."""

import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from app.services.cf7_candidate_contract import digest
from app.services.cf7_real_contract_preview import preview
from app.services.cf7_real_encoding import encode, summarize, validate_saved
from app.services.cf7_static_inspection import inspect_isolated
from app.services.form_execution_plan import PlanError
from app.services.form_input_preparation import prepare
from bs4 import BeautifulSoup
from contract_probe import local_post
from protocol import classify, observe


def logical_html(html, origin):
    logical = "https://managed.example"
    # WP JSON escapes slashes. Map only the fixed lab origin in both encodings.
    return html.replace(origin, logical).replace(
        origin.replace("/", r"\/"), logical.replace("/", r"\/")
    )


def make_inputs(html, origin, page_url, version):
    if os.environ.get("CF7_PROTOCOL_LAB") != "1" or version not in {"6.1.4", "6.2"}:
        raise ValueError("Explicit pinned lab required")
    observed = observe(html, origin, plugin_version=version)
    forms = BeautifulSoup(html, "html.parser").find_all("form")
    targets = [
        i for i, form in enumerate(forms) if "wpcf7-form" in (form.get("class") or [])
    ]
    if len(targets) != 1:
        raise ValueError("One fixed CF7 form required")
    # Lexical HTTPS placeholder for non-executable metadata only; never a network destination.
    logical = "https://managed.example"
    static = inspect_isolated(
        logical_html(html, origin), page_url.replace(origin, logical), targets[0]
    )
    evidence = static.get("contract_evidence")
    if not evidence or evidence["plugin_version"] != version:
        raise ValueError("Actual fixture DOM is unsupported; do not strip constraints")
    expected = {
        "your-name": "Lab operator",
        "your-email": "operator@example.com",
        "your-message": "固定受信検証😀\nLF\rCR\r\nCRLF\n",
    }
    if {c["name"] for c in evidence["controls"]} != set(expected):
        raise ValueError("Fixed encoding cohort required")
    fields = [
        {"name": c["name"], "field_type": c["kind"], "position": i}
        for i, c in enumerate(evidence["controls"])
    ]
    material = {
        "technical_diagnostic": {
            "boundary": "TECHNICAL_HOLD",
            "route": "CF7_CANDIDATE",
        },
        **{
            key: str(UUID(int=i))
            for i, key in enumerate(
                ("project_id", "company_id", "profile_id", "draft_id"), 1
            )
        },
        "form_url": evidence["form_url"],
        "profile_fingerprint": digest(evidence),
        "draft_hash": digest(expected),
        "items": [
            {
                "position": i,
                "name": c["name"],
                "label": c["name"],
                "required": c["required"],
                "review_state": "UNAPPROVED_DRAFT_VALUE"
                if c["kind"] == "textarea"
                else "SENDER_VALUE_PROPOSED",
                "proposed_value": expected[c["name"]],
            }
            for i, c in enumerate(evidence["controls"])
        ],
    }
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    observation = {
        "freshness": "CURRENT",
        "expires_at": expiry,
        "structure_status": "SAME_STRUCTURE",
        "method_is_post": True,
        "cf7_static": static,
    }
    report = prepare(material, fields, observation, source_hash=digest(evidence))
    report.update(
        review_status="RECORDED",
        reviewed_by=str(UUID(int=5)),
        reviewed_at=datetime.now(timezone.utc),
        review_expires_at=expiry,
    )
    return observed, report, observation


def verify_real_encoding(origin, report, fixture, check, version):
    created = json.loads(fixture("create-encoding"))
    if not created["page_url"].startswith(origin + "/"):
        raise ValueError("Fixed local fixture URL required")
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        page = client.get(created["page_url"])
        report["encoding_fixture_diagnostic"] = inspect_isolated(
            logical_html(page.text, origin),
            created["page_url"].replace(origin, "https://managed.example"),
            next(
                (
                    i
                    for i, f in enumerate(
                        BeautifulSoup(page.text, "html.parser").find_all("form")
                    )
                    if "wpcf7-form" in (f.get("class") or [])
                ),
                0,
            ),
        )
        check(
            "encoding fixture local rendered page",
            page.status_code == 200,
            {"http": page.status_code, "location": page.headers.get("location")},
        )
        observed, inputs, observation = make_inputs(
            page.text, origin, created["page_url"], version
        )
        check("encoding fixture ID binding", observed.form_id == created["form_id"])
        current = preview(inputs, observation)
        expected_hash = current["contract_hash"]
        encoded = encode(inputs, observation, expected_contract_hash=expected_hash)
        saved = summarize(encoded)
        expected_parts = current["contract"]["parts"]
        expected_values = {
            p["name"]: hashlib.sha256(
                p["value"]
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .replace("\n", "\r\n")
                .encode()
            ).hexdigest()
            for p in expected_parts
        }
        before_negatives = json.loads(fixture("evidence"))
        rejected = []
        for change in ("draft", "target", "order", "expired", "wire_hash", "maxlength"):
            revised, changed_observation, changed_saved = (
                copy.deepcopy(inputs),
                copy.deepcopy(observation),
                copy.deepcopy(saved),
            )
            if change == "draft":
                revised["snapshot"]["rows"][-1]["values"] = ["Changed"]
            if change == "target":
                revised["snapshot"]["form_url"] = "https://other.example/contact"
            if change == "order":
                changed_observation["cf7_static"]["contract_evidence"][
                    "dom_order"
                ].reverse()
            if change == "expired":
                revised["review_expires_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat()
            if change == "wire_hash":
                changed_saved["wire_sha256"] = "0" * 64
            if change == "maxlength":
                changed_observation["cf7_static"]["contract_evidence"]["controls"][0][
                    "maxlength"
                ] = 1
            try:
                validate_saved(
                    changed_saved,
                    revised,
                    changed_observation,
                    expected_contract_hash=expected_hash,
                )
            except PlanError:
                rejected.append(change)
        check(
            "encoding changed snapshots rejected before POST",
            len(rejected) == 6 and before_negatives == json.loads(fixture("evidence")),
        )
        records = []
        for mode, expected in (("capture", "RECEIPT_REPORTED"), ("fail", "UNKNOWN")):
            fixture("mode", mode)
            before = json.loads(fixture("evidence"))
            validate_saved(
                saved, inputs, observation, expected_contract_hash=expected_hash
            )
            response = local_post(
                client, observed, encoded.content_type, encoded.body, origin
            )
            report["feedback_post_count"] += 1
            after = json.loads(fixture("evidence"))
            receipt = classify(
                response.status_code,
                response.headers.get("content-type", ""),
                response.content,
                observed,
            )
            received = after["submissions"][-1]
            check(
                "encoding " + version + " " + mode + " captured reception",
                receipt == expected
                and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
                and len(after["submissions"]) == len(before["submissions"]) + 1
                and received["raw_post_order"] == [p["name"] for p in expected_parts]
                and received["raw_value_hashes"] == expected_values,
            )
            records.append(
                {
                    "mode": mode,
                    "classification": receipt,
                    "ordered_names_match": True,
                    "value_hashes_match": True,
                }
            )
        report["real_preview_encoding"] = {
            "plugin_version": version,
            "synthetic_input_confirmation": True,
            "actual_dom_constraints_preserved": True,
            "candidate_urls_executed": False,
            "logical_origin_is_placeholder": True,
            "encoding": saved,
            "cases": records,
            "negative_cases_rejected": rejected,
            "local_feedback_posts": 2,
            "real_email_sent": 0,
            "real_form_sent": 0,
            "approvals_created": 0,
        }
