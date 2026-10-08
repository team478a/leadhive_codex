"""One fixed extra hidden fixture, never an arbitrary token copying path."""

import hashlib
import json
import os
from dataclasses import replace

import httpx
from app.services.cf7_candidate_contract import digest
from app.services.cf7_extra_hidden_contract import (
    ExtraHidden,
    ExtraHiddenCandidate,
    snapshot,
    validate_snapshot,
    wire,
)
from bs4 import BeautifulSoup
from contract_probe import EMAIL, local_post, make_candidate
from group_probe import decode_parts, grouped
from protocol import classify, observe

NAME = "leadhive_lab_context"
VALUE = "fixture-business-context"


def make_hidden_candidate(html, origin):
    if os.environ.get("CF7_PROTOCOL_LAB") != "1":
        raise ValueError("Explicit lab opt-in required")
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.select("form.wpcf7-form")
    if len(forms) != 8:
        raise ValueError("Fixed eight-form fixture required")
    form = forms[7]
    extras = form.select('[name="leadhive_lab_context"]')
    if len(extras) != 1:
        raise ValueError("Exactly one fixed extra hidden required")
    extra = extras[0]
    if (
        extra.name != "input"
        or extra.get("type") != "hidden"
        or extra.get("value") != VALUE
        or extra.has_attr("disabled")
        or extra.has_attr("onclick")
    ):
        raise ValueError("Unknown extra hidden meaning/value")
    fingerprint = hashlib.sha256(str(form).encode()).hexdigest()
    extra.decompose()
    for other in forms:
        if other is not form:
            other.decompose()
    cleaned = str(soup)
    base = make_candidate(cleaned, origin).model_copy(
        update={"dom_fingerprint": fingerprint}
    )
    plan = ExtraHiddenCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=base,
        extra=ExtraHidden(
            name="leadhive_lab_context",
            value="fixture-business-context",
            purpose="FIXED_LAB_ROUTING_CONTEXT",
        ),
    )
    return plan, replace(observe(cleaned, origin), fingerprint=fingerprint)


def verified_wire(saved, plan):
    base = plan.base
    validate_snapshot(
        saved,
        plan,
        expected_hash=digest(saved),
        expected_version=1,
        project_id=base.project_id,
        company_id=base.company_id,
        source_draft_id=base.source_draft_id,
        form_profile_id=base.form_profile_id,
    )
    return wire(plan)


def verify_hidden(
    client, html, origin, output, report, fixture, check, command, assets, page_url
):
    initial = json.loads(fixture("evidence"))
    start = report["feedback_post_count"]
    plan, observed = make_hidden_candidate(html, origin)
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
                "extra_hidden_value_hashes", []
            ),
        }
        records.append(detail)
        check(
            "extra hidden " + name,
            response.status_code == 200
            and status in expected
            and delta == int(status in {"mail_sent", "mail_failed"})
            and len(after["submissions"]) == len(before["submissions"]) + 1
            and receipt == ("RECEIPT_REPORTED" if status == "mail_sent" else "UNKNOWN"),
            detail,
        )
        return after["mail_calls"][-1] if delta else None

    captured = submit("fixed value", kind, body, {"mail_sent"})
    check(
        "extra hidden fixed value preserved",
        records[-1]["posted_value_hashes"]
        == [hashlib.sha256(VALUE.encode()).hexdigest()],
    )
    for name, values in (
        ("omitted negative", ()),
        ("changed negative", ("OTHER_FIXTURE_CONTEXT",)),
        ("duplicate negative", (VALUE, "OTHER_FIXTURE_CONTEXT")),
    ):
        request = httpx.Request(
            "POST",
            origin,
            files=[(n, (None, v)) for n, v in parts if n != NAME]
            + [(NAME, (None, v)) for v in values],
        )
        submit(
            name,
            request.headers["content-type"],
            request.read(),
            {"mail_sent", "validation_failed"},
        )
    submit("mail failure unknown", kind, body, {"mail_failed"}, "fail")
    fixture("mode", "capture")
    before = json.loads(fixture("evidence"))
    browser = json.loads(
        command(
            "node",
            str(assets / "browser_probe.cjs"),
            page_url,
            EMAIL,
            "extra_hidden",
            env=os.environ.copy(),
            timeout=90,
        )
    )
    report["feedback_post_count"] += len(browser["posts"])
    after = json.loads(fixture("evidence"))
    equivalent = grouped(browser["posts"][0]["fields"]) == grouped(parts)
    check(
        "extra hidden browser equivalence",
        len(browser["posts"]) == 1
        and equivalent
        and browser["posts"][0]["url"] == observed.endpoint
        and len(after["submissions"]) == len(before["submissions"]) + 1
        and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
        and after["mail_calls"][-1] == captured,
    )
    (output / "hidden-snapshot.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "hidden-browser-wire.json").write_text(
        json.dumps(browser, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["extra_hidden_contract"] = {
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
