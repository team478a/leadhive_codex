"""Fixed local radio fixture only, no candidate URL execution."""

import hashlib
import json
import os
from dataclasses import replace

import httpx
from app.services.cf7_candidate_contract import digest
from app.services.cf7_radio_contract import (
    RadioCandidate,
    RadioGroup,
    snapshot,
    validate_snapshot,
    wire,
)
from bs4 import BeautifulSoup
from contract_probe import EMAIL, local_post, make_candidate
from group_probe import decode_parts, grouped
from protocol import classify, observe

VALUES = ("SNS運用", "OEM")


def make_radio_candidate(html, origin, selected):
    if os.environ.get("CF7_PROTOCOL_LAB") != "1" or selected not in VALUES:
        raise ValueError("Explicit fixed fixture and choice required")
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.select("form.wpcf7-form")
    form = forms[6]
    groups = form.select(".wpcf7-radio")
    if len(groups) != 1:
        raise ValueError("Exactly one fixture radio group required")
    group = groups[0]
    fields = group.select("input, textarea, select")
    if len(fields) != 2 or group.select(
        "[onclick], [onsubmit], [formaction], [formmethod]"
    ):
        raise ValueError("Unexpected fixture radio shape")
    options = []
    for key, field, value in zip(("social", "oem"), fields, VALUES, strict=True):
        label = field.find_parent("label")
        if (
            field.get("type") != "radio"
            or field.get("name") != "topic"
            or field.get("value") != value
            or field.has_attr("disabled")
            or label is None
            or label.get_text(strip=True) != value
        ):
            raise ValueError("Unexpected radio option")
        options.append(
            {
                "option_id": key,
                "label": value,
                "value": value,
                "initially_checked": field.has_attr("checked"),
            }
        )
    fingerprint = hashlib.sha256(str(form).encode()).hexdigest()
    group.decompose()
    for other in forms:
        if other is not form:
            other.decompose()
    cleaned = str(soup)
    base = make_candidate(cleaned, origin).model_copy(
        update={"dom_fingerprint": fingerprint}
    )
    proposal = RadioCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=base,
        group=RadioGroup.model_validate(
            {
                "group_id": "topic",
                "name": "topic",
                "label": "Business topic",
                "purpose": "BUSINESS_SELECTION",
                "options": tuple(options),
                "choices": tuple(
                    {"option_id": o["option_id"], "checked": o["value"] == selected}
                    for o in options
                ),
            }
        ),
    )
    return proposal, replace(observe(cleaned, origin), fingerprint=fingerprint)


def verified_wire(saved, current):
    base = current.base
    validate_snapshot(
        saved,
        current,
        expected_hash=digest(saved),
        expected_version=1,
        project_id=base.project_id,
        company_id=base.company_id,
        source_draft_id=base.source_draft_id,
        form_profile_id=base.form_profile_id,
    )
    return wire(current)


def verify_radio(
    client, html, origin, output, report, fixture, check, command, assets, page_url
):
    initial = json.loads(fixture("evidence"))
    start = report["feedback_post_count"]
    plan, observed = make_radio_candidate(html, origin, "OEM")
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
        detail = {
            "case": name,
            "status": status,
            "classification": receipt,
            "mail_capture_delta": delta,
            "posted_value_hashes": after["submissions"][-1].get(
                "radio_value_hashes", []
            ),
        }
        records.append(detail)
        check(
            "radio " + name,
            response.status_code == 200
            and status in expected
            and delta == int(status in {"mail_sent", "mail_failed"})
            and len(after["submissions"]) == len(before["submissions"]) + 1
            and receipt == ("RECEIPT_REPORTED" if status == "mail_sent" else "UNKNOWN"),
            detail,
        )
        return after["mail_calls"][-1] if delta else None

    captured = submit("explicit one", kind, body, {"mail_sent"})
    check(
        "radio explicit value preserved",
        records[-1]["posted_value_hashes"] == [hashlib.sha256(b"OEM").hexdigest()],
    )
    for name, values, expected in (
        ("empty negative", (), {"validation_failed"}),
        ("foreign negative", ("UNKNOWN",), {"validation_failed", "mail_sent"}),
        ("multiple negative", VALUES, {"validation_failed", "mail_sent"}),
    ):
        request = httpx.Request(
            "POST",
            origin,
            files=[(n, (None, v)) for n, v in parts if n != "topic"]
            + [("topic", (None, v)) for v in values],
        )
        submit(name, request.headers["content-type"], request.read(), expected)
    submit("mail failure unknown", kind, body, {"mail_failed"}, "fail")
    fixture("mode", "capture")
    before = json.loads(fixture("evidence"))
    browser = json.loads(
        command(
            "node",
            str(assets / "browser_probe.cjs"),
            page_url,
            EMAIL,
            "radio",
            env=os.environ.copy(),
            timeout=90,
        )
    )
    report["feedback_post_count"] += len(browser["posts"])
    after = json.loads(fixture("evidence"))
    equivalent = grouped(browser["posts"][0]["fields"]) == grouped(parts)
    check(
        "radio browser equivalence",
        len(browser["posts"]) == 1
        and equivalent
        and browser["posts"][0]["url"] == observed.endpoint
        and len(after["submissions"]) == len(before["submissions"]) + 1
        and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
        and after["mail_calls"][-1] == captured,
    )
    (output / "radio-snapshot.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "radio-browser-wire.json").write_text(
        json.dumps(browser, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["radio_contract"] = {
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
