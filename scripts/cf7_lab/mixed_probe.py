"""Controlled nine-form fixture only. Never executes candidate URLs."""

import copy
import hashlib
import json
import os
from dataclasses import replace

import httpx
from app.services.cf7_candidate_contract import digest
from app.services.cf7_mixed_contract import (
    MixedCandidate,
    snapshot,
    validate_snapshot,
    wire,
)
from bs4 import BeautifulSoup
from contract_probe import EMAIL, local_post
from group_probe import decode_parts, grouped, make_group_candidate
from hidden_probe import make_hidden_candidate
from protocol import classify
from radio_probe import make_radio_candidate


def make_mixed_candidate(html, origin):
    if os.environ.get("CF7_PROTOCOL_LAB") != "1":
        raise ValueError("Explicit lab opt-in required")
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.select("form.wpcf7-form")
    if len(forms) != 9:
        raise ValueError("Fixed nine-form fixture required")
    original = forms[8]
    fingerprint = hashlib.sha256(str(original).encode()).hexdigest()

    def subset(keep, count):
        page = copy.deepcopy(soup)
        for form in page.select("form.wpcf7-form"):
            form.decompose()
        target = copy.deepcopy(original)
        for selector in (
            ".wpcf7-checkbox",
            ".wpcf7-radio",
            '[name="leadhive_lab_context"]',
        ):
            if selector != keep:
                for field in target.select(selector):
                    field.decompose()
        # Existing fixed mappers select their fixture index; all clones share one ID.
        for _ in range(count):
            page.append(copy.deepcopy(target))
        return str(page)

    groups, observed = make_group_candidate(
        subset(".wpcf7-checkbox", 5),
        origin,
        4,
        required=True,
        selected=("SNS運用", "OEM"),
    )
    radio, _ = make_radio_candidate(subset(".wpcf7-radio", 7), origin, "OEM")
    hidden, _ = make_hidden_candidate(
        subset('[name="leadhive_lab_context"]', 8), origin
    )
    base = groups.base.model_copy(update={"dom_fingerprint": fingerprint})
    if groups.base.model_copy(
        update={"dom_fingerprint": fingerprint}
    ) != radio.base.model_copy(
        update={"dom_fingerprint": fingerprint}
    ) or base != hidden.base.model_copy(update={"dom_fingerprint": fingerprint}):
        raise ValueError("Mixed fixture components disagree")
    plan = MixedCandidate(
        source_kind="CONTROLLED_FIXTURE",
        groups=groups.model_copy(update={"base": base}),
        radio=radio.model_copy(update={"base": base}),
        hidden=hidden.model_copy(update={"base": base}),
    )
    return plan, replace(observed, fingerprint=fingerprint)


def verified_wire(saved, plan):
    base = plan.groups.base
    validate_snapshot(
        saved,
        plan,
        expected_hash=digest(saved),
        expected_version=base.payload_version,
        project_id=base.project_id,
        company_id=base.company_id,
        source_draft_id=base.source_draft_id,
        form_profile_id=base.form_profile_id,
    )
    return wire(plan)


def verify_mixed(
    client, html, origin, output, report, fixture, check, command, assets, page_url
):
    initial = json.loads(fixture("evidence"))
    start = report["feedback_post_count"]
    plan, observed = make_mixed_candidate(html, origin)
    saved = snapshot(plan)
    kind, body = verified_wire(saved, plan)
    parts = decode_parts(kind, body)
    records = []

    def submit(name, content_type, payload, expected, mode="capture"):
        fixture("mode", mode)
        before = json.loads(fixture("evidence"))
        report["feedback_post_count"] += 1
        response = local_post(client, observed, content_type, payload, origin)
        after = json.loads(fixture("evidence"))
        status = response.json().get("status")
        delta = len(after["mail_calls"]) - len(before["mail_calls"])
        receipt = classify(
            response.status_code,
            response.headers.get("content-type", ""),
            response.content,
            observed,
        )
        records.append(
            {
                "case": name,
                "status": status,
                "classification": receipt,
                "mail_capture_delta": delta,
            }
        )
        check(
            "mixed " + name,
            response.status_code == 200
            and status == expected
            and delta == int(status in {"mail_sent", "mail_failed"})
            and len(after["submissions"]) == len(before["submissions"]) + 1
            and receipt == ("RECEIPT_REPORTED" if status == "mail_sent" else "UNKNOWN"),
        )
        return after["mail_calls"][-1] if delta else None

    captured = submit("explicit combined values", kind, body, "mail_sent")
    for name in ("services[]", "topic"):
        request = httpx.Request(
            "POST", origin, files=[(n, (None, v)) for n, v in parts if n != name]
        )
        submit(
            "missing " + name,
            request.headers["content-type"],
            request.read(),
            "validation_failed",
        )
    submit("mail failure unknown", kind, body, "mail_failed", "fail")
    fixture("mode", "capture")
    before = json.loads(fixture("evidence"))
    browser = json.loads(
        command(
            "node",
            str(assets / "browser_probe.cjs"),
            page_url,
            EMAIL,
            "mixed",
            env=os.environ.copy(),
            timeout=90,
        )
    )
    report["feedback_post_count"] += len(browser["posts"])
    after = json.loads(fixture("evidence"))
    equivalent = len(browser["posts"]) == 1 and grouped(
        browser["posts"][0]["fields"]
    ) == grouped(parts)
    check(
        "mixed actual browser equivalence",
        equivalent
        and browser["posts"][0]["url"] == observed.endpoint
        and len(after["submissions"]) == len(before["submissions"]) + 1
        and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
        and after["mail_calls"][-1] == captured,
    )
    for filename, data in (
        ("mixed-snapshot.json", saved),
        ("mixed-browser-wire.json", browser),
    ):
        (output / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    report["mixed_contract"] = {
        "contract_version": plan.contract_version,
        "cases": records,
        "wire_sha256": saved["wire_sha256"],
        "wire_size": saved["wire_size"],
        "browser_grouped_fields_equal": equivalent,
        "browser_full_part_order_equal": [
            tuple(p) for p in browser["posts"][0]["fields"]
        ]
        == parts,
        "feedback_post_count": report["feedback_post_count"] - start,
        "submission_delta": len(after["submissions"]) - len(initial["submissions"]),
        "mail_capture_delta": len(after["mail_calls"]) - len(initial["mail_calls"]),
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
