"""Fixed managed-fixture group protocol; never executes candidate HTTPS URLs."""

import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import replace
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from contract_probe import EMAIL, local_post, make_candidate
from protocol import classify, observe

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.services.cf7_candidate_contract import digest
from app.services.cf7_checkbox_group_contract import (
    CheckboxGroup,
    GroupCandidate,
    snapshot,
    validate_snapshot,
    wire,
)

VALUES = ("SNS運用", "Website", "OEM")


def make_group_candidate(html, origin, index, *, required, selected):
    if os.environ.get("CF7_PROTOCOL_LAB") != "1" or index not in (4, 5):
        raise ValueError("Only explicit managed group fixtures are supported")
    if (
        required is not (index == 4)
        or set(selected) - set(VALUES)
        or len(selected) != len(set(selected))
    ):
        raise ValueError("Unknown fixture or selection")
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.select("form.wpcf7-form")
    form = forms[index]
    groups = form.select(".wpcf7-checkbox")
    if len(groups) != 1:
        raise ValueError("Exactly one fixture checkbox group required")
    group = groups[0]
    fields = group.select("input, textarea, select")
    if group.select("[onclick], [onsubmit], [formaction], [formmethod]"):
        raise ValueError("Custom group execution path")
    if len(fields) != 3:
        raise ValueError("Unexpected fixture option count")
    options = []
    for option_id, field, expected in zip(
        ("social", "web", "oem"), fields, VALUES, strict=True
    ):
        label = field.find_parent("label")
        if (
            field.get("type") != "checkbox"
            or field.get("name") != "services[]"
            or field.get("value") != expected
            or field.has_attr("disabled")
            or field.has_attr("onclick")
            or label is None
            or label.get_text(strip=True) != expected
        ):
            raise ValueError("Unexpected group fixture shape")
        options.append(
            {
                "option_id": option_id,
                "label": expected,
                "value": expected,
                "initially_checked": field.has_attr("checked"),
            }
        )
    full_fingerprint = hashlib.sha256(str(form).encode()).hexdigest()
    group.decompose()
    for other in forms:
        if other is not form:
            other.decompose()
    cleaned = str(soup)
    base = make_candidate(cleaned, origin)
    # Preserve original full group DOM binding, not just the stripped scalar form.
    base = base.model_copy(update={"dom_fingerprint": full_fingerprint})
    candidate = GroupCandidate(
        source_kind="CONTROLLED_FIXTURE",
        base=base,
        groups=(
            CheckboxGroup.model_validate(
                {
                    "group_id": "services",
                    "name": "services[]",
                    "label": "Business services",
                    "purpose": "BUSINESS_SELECTION",
                    "required": required,
                    "min_selected": int(required),
                    "max_selected": 3,
                    "options": tuple(options),
                    "choices": tuple(
                        {
                            "option_id": option["option_id"],
                            "checked": option["value"] in selected,
                        }
                        for option in options
                    ),
                }
            ),
        ),
    )
    return candidate, replace(observe(cleaned, origin), fingerprint=full_fingerprint)


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


def decode_parts(content_type, body):
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        + body
    )
    if not message.is_multipart() or message.defects:
        raise ValueError("Malformed group multipart")
    result = []
    for part in message.iter_parts():
        value = part.get_payload(decode=True)
        name = part.get_param("name", header="content-disposition")
        if (
            not isinstance(value, bytes)
            or not isinstance(name, str)
            or part.get_filename()
            or part.defects
        ):
            raise ValueError("Unexpected multipart part")
        result.append((name, value.decode("utf-8")))
    return result


def grouped(parts):
    result = defaultdict(list)
    for name, value in parts:
        result[name].append(value)
    return dict(result)


def verify_groups(
    client, html, origin, output, report, fixture, check, command, assets, page_url
):
    initial = json.loads(fixture("evidence"))
    start_posts = report["feedback_post_count"]
    records = []
    required, observed = make_group_candidate(
        html, origin, 4, required=True, selected=(VALUES[0], VALUES[2])
    )
    saved = snapshot(required)
    content_type, body = verified_wire(saved, required)
    decoded = decode_parts(content_type, body)
    (output / "group-snapshot.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "group-wire.bin").write_bytes(body)

    def submit(
        name, observed, content_type, body, *, expected, mode="capture", values=()
    ):
        fixture("mode", mode)
        before = json.loads(fixture("evidence"))
        report["feedback_post_count"] += 1
        response = local_post(client, observed, content_type, body, origin)
        after = json.loads(fixture("evidence"))
        result = response.json()
        status = result.get("status")
        mail_delta = len(after["mail_calls"]) - len(before["mail_calls"])
        expected_mail = int(status in {"mail_sent", "mail_failed"})
        receipt = classify(
            response.status_code,
            response.headers.get("content-type", ""),
            response.content,
            observed,
        )
        detail = {
            "case": name,
            "http": response.status_code,
            "status": status,
            "classification": receipt,
            "mail_capture_delta": mail_delta,
            "posted_group_hashes": after["submissions"][-1].get(
                "group_value_hashes", []
            ),
            "invalid_field_count": len(result.get("invalid_fields", [])),
        }
        records.append(detail)
        check(
            "group " + name,
            response.status_code == 200
            and status in expected
            and mail_delta == expected_mail
            and len(after["submissions"]) == len(before["submissions"]) + 1
            and receipt == ("RECEIPT_REPORTED" if status == "mail_sent" else "UNKNOWN")
            and (
                values is None
                or detail["posted_group_hashes"]
                == [hashlib.sha256(v.encode()).hexdigest() for v in values]
            ),
            detail,
        )
        return after["mail_calls"][-1] if mail_delta else None

    captured = submit(
        "required two values",
        observed,
        content_type,
        body,
        expected={"mail_sent"},
        values=(VALUES[0], VALUES[2]),
    )

    # Negative server probes deliberately bypass the non-executable contract.
    # They are bounded lab tests, never a dispatch path or Human-approved payload.
    def raw_probe(values):
        request = httpx.Request(
            "POST",
            origin,
            files=[
                (name, (None, value)) for name, value in decoded if name != "services[]"
            ]
            + [("services[]", (None, value)) for value in values],
        )
        return request.headers["content-type"], request.read()

    empty_type, empty_body = raw_probe(())
    submit(
        "required empty negative probe",
        observed,
        empty_type,
        empty_body,
        expected={"validation_failed"},
    )
    optional, optional_observed = make_group_candidate(
        html, origin, 5, required=False, selected=()
    )
    optional_type, optional_body = verified_wire(snapshot(optional), optional)
    submit(
        "optional empty",
        optional_observed,
        optional_type,
        optional_body,
        expected={"mail_sent"},
    )
    unknown_type, unknown_body = raw_probe(("UNKNOWN_FIXTURE_VALUE",))
    # Record actual behavior rather than guessing how CF7 validates foreign values.
    submit(
        "foreign value negative probe",
        observed,
        unknown_type,
        unknown_body,
        expected={"mail_sent", "validation_failed"},
        values=None,
    )
    submit(
        "mail failure remains unknown",
        observed,
        content_type,
        body,
        expected={"mail_failed"},
        mode="fail",
        values=(VALUES[0], VALUES[2]),
    )
    fixture("mode", "capture")
    before_browser = json.loads(fixture("evidence"))
    browser = json.loads(
        command(
            "node",
            str(assets / "browser_probe.cjs"),
            page_url,
            EMAIL,
            "groups_required",
            env=os.environ.copy(),
            timeout=90,
        )
    )
    report["feedback_post_count"] += len(browser["posts"])
    after_browser = json.loads(fixture("evidence"))
    browser_parts = browser["posts"][0]["fields"]
    equivalent = grouped(browser_parts) == grouped(decoded)
    check(
        "group actual browser ordered values and mail",
        len(browser["posts"]) == 1
        and equivalent
        and browser["posts"][0]["url"] == observed.endpoint
        and len(after_browser["mail_calls"]) == len(before_browser["mail_calls"]) + 1
        and len(after_browser["submissions"]) == len(before_browser["submissions"]) + 1
        and after_browser["mail_calls"][-1] == captured
        and after_browser["submissions"][-1].get("group_value_hashes")
        == [hashlib.sha256(v.encode()).hexdigest() for v in (VALUES[0], VALUES[2])],
    )
    (output / "group-browser-wire.json").write_text(
        json.dumps(browser, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    final = json.loads(fixture("evidence"))
    report["group_contract"] = {
        "contract_version": required.contract_version,
        "cases": records,
        "contract_hash": saved["contract_hash"],
        "wire_sha256": saved["wire_sha256"],
        "wire_size": saved["wire_size"],
        "browser_grouped_fields_equal": equivalent,
        "browser_full_part_order_equal": [tuple(v) for v in browser_parts] == decoded,
        "feedback_post_count": report["feedback_post_count"] - start_posts,
        "mail_capture_delta": len(final["mail_calls"]) - len(initial["mail_calls"]),
        "submission_delta": len(final["submissions"]) - len(initial["submissions"]),
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
