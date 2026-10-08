"""Successful control order from fixed rendered DOM; never real-site execution."""

import json
import os

from app.services.cf7_candidate_contract import digest
from app.services.cf7_ordered_contract import (
    OrderedCandidate,
    PartRef,
    snapshot,
    validate_snapshot,
    values,
    wire,
)
from bs4 import BeautifulSoup
from contract_probe import EMAIL, local_post
from group_probe import decode_parts
from mixed_probe import make_mixed_candidate
from protocol import classify


def make_ordered_candidate(html, origin):
    mixed, observed = make_mixed_candidate(html, origin)
    form = BeautifulSoup(html, "html.parser").select("form.wpcf7-form")[8]
    lookup = values(mixed)
    options = {
        ("CHECKBOX", g.name, o.option_id): o.value
        for g in mixed.groups.groups
        for o in g.options
    }
    options.update(
        {
            ("RADIO", mixed.radio.group.name, o.option_id): o.value
            for o in mixed.radio.group.options
        }
    )
    order = []
    for field in form.select("input[name], textarea[name], select[name]"):
        name = str(field.get("name"))
        matches = [k for k in lookup if k[1] == name]
        if not matches:
            # Unselected known option is not a successful control.
            if any(
                k[1] == name and v == field.get("value") for k, v in options.items()
            ):
                continue
            raise ValueError("Unknown named control in full DOM")
        if field.get("type") in ("checkbox", "radio") and any(
            k[0] in ("CHECKBOX", "RADIO") for k in matches
        ):
            matches = [k for k in matches if lookup[k] == field.get("value")]
            if not matches and any(
                k[1] == name and v == field.get("value") for k, v in options.items()
            ):
                continue
        if len(matches) != 1 or field.has_attr("disabled"):
            raise ValueError("Ambiguous or disabled successful control")
        kind, name, option_id = matches[0]
        order.append(
            PartRef.model_validate({"kind": kind, "name": name, "option_id": option_id})
        )
    return OrderedCandidate(
        source_kind="CONTROLLED_FIXTURE", mixed=mixed, order=tuple(order)
    ), observed


def verified_wire(saved, plan):
    base = plan.mixed.groups.base
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


def verify_ordered(
    client, html, origin, output, report, fixture, check, command, assets, page_url
):
    initial = json.loads(fixture("evidence"))
    start = report["feedback_post_count"]
    plan, observed = make_ordered_candidate(html, origin)
    saved = snapshot(plan)
    kind, body = verified_wire(saved, plan)
    parts = decode_parts(kind, body)
    records = []
    captured = None
    for mode, expected in (("capture", "mail_sent"), ("fail", "mail_failed")):
        fixture("mode", mode)
        before = json.loads(fixture("evidence"))
        report["feedback_post_count"] += 1
        response = local_post(client, observed, kind, body, origin)
        after = json.loads(fixture("evidence"))
        receipt = classify(
            response.status_code,
            response.headers.get("content-type", ""),
            response.content,
            observed,
        )
        delta = len(after["mail_calls"]) - len(before["mail_calls"])
        check(
            "ordered " + mode,
            response.status_code == 200
            and response.json().get("status") == expected
            and delta == 1
            and len(after["submissions"]) == len(before["submissions"]) + 1
            and receipt == ("RECEIPT_REPORTED" if mode == "capture" else "UNKNOWN"),
        )
        records.append(
            {
                "case": mode,
                "status": expected,
                "classification": receipt,
                "mail_capture_delta": delta,
            }
        )
        if mode == "capture":
            captured = after["mail_calls"][-1]
    revised = plan.model_copy(update={"order": tuple(reversed(plan.order))})
    try:
        verified_wire(saved, revised)
    except ValueError:
        rejected = True
    else:
        rejected = False
    check("ordered revision stopped before HTTP", rejected)
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
    equal = (
        len(browser["posts"]) == 1
        and [tuple(p) for p in browser["posts"][0]["fields"]] == parts
    )
    check(
        "ordered browser full part order and mail",
        equal
        and browser["posts"][0]["url"] == observed.endpoint
        and len(after["submissions"]) == len(before["submissions"]) + 1
        and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
        and after["mail_calls"][-1] == captured,
    )
    for filename, data in (
        ("ordered-snapshot.json", saved),
        ("ordered-browser-wire.json", browser),
    ):
        (output / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    report["ordered_contract"] = {
        "contract_version": plan.contract_version,
        "cases": records,
        "wire_sha256": saved["wire_sha256"],
        "wire_size": saved["wire_size"],
        "browser_full_part_order_equal": equal,
        "revision_rejected_without_http": rejected,
        "part_count": len(parts),
        "feedback_post_count": report["feedback_post_count"] - start,
        "submission_delta": len(after["submissions"]) - len(initial["submissions"]),
        "mail_capture_delta": len(after["mail_calls"]) - len(initial["mail_calls"]),
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
