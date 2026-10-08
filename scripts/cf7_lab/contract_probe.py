"""Managed lab bridge for candidate WIRE only; never executes candidate URLs."""

import hashlib
import json
import os
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from bs4 import BeautifulSoup
from protocol import classify, observe

# Load only the pure contract modules. No app.main, config, database or dispatcher.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.services.cf7_candidate_contract import (
    CF7Candidate,
    Control,
    Selection,
    digest,
    snapshot,
    validate_snapshot,
    wire,
)
from app.services.form_execution_plan import InputValue

LOGICAL_ORIGIN = "https://managed.example"
EMAIL = "operator@example.com"
MESSAGE = "Lab fixture only 日本語\n第二行"


def make_candidate(html, origin):
    if os.environ.get("CF7_PROTOCOL_LAB") != "1":
        raise ValueError("Explicit lab opt-in required")
    item = observe(html, origin)
    suffix = f"contact-form-7/v1/contact-forms/{item.form_id}/feedback"
    roots = {
        origin + "/wp-json/",
        origin + "/?rest_route=/",
        origin + "/index.php?rest_route=/",
    }
    root = item.endpoint.removesuffix(suffix)
    if root not in roots:
        raise ValueError("Unexpected lab route")
    form = BeautifulSoup(html, "html.parser").select("form.wpcf7-form")[0]
    controls = []
    for field in form.select("input[name], textarea[name]"):
        if field.get("type") == "hidden":
            continue
        kind = "textarea" if field.name == "textarea" else field.get("type", "text")
        if not isinstance(kind, str) or not isinstance(field["name"], str):
            raise TypeError("Ambiguous control attributes")
        label = field.find_parent("label")
        if kind == "checkbox":
            acceptance = field.find_parent(class_="wpcf7-acceptance")
            classes = acceptance.get("class") if acceptance is not None else None
            if not isinstance(classes, list) or {"optional", "invert"} & set(classes):
                raise ValueError(
                    "Only the standard lab acceptance fixture is supported"
                )
        controls.append(
            Control.model_validate(
                {
                    "name": field["name"],
                    "kind": kind,
                    "required": kind == "checkbox"
                    or field.get("aria-required") == "true"
                    or field.has_attr("required"),
                    "label": label.get_text(" ", strip=True) if label else "",
                    "checkbox_value": str(field.get("value", ""))
                    if kind == "checkbox"
                    else "",
                }
            )
        )
    if item.fields != ("your-name", "your-email", "your-message", "consent"):
        raise ValueError("Only this lab's fixed four fields are supported")
    logical_root = LOGICAL_ORIGIN + root.removeprefix(origin)
    fields = {
        "your-name": "Lab operator",
        "your-email": EMAIL,
        "your-message": MESSAGE,
        "consent": "1",
    }
    return CF7Candidate(
        project_id=UUID(int=1),
        company_id=UUID(int=2),
        source_draft_id=UUID(int=3),
        form_profile_id=UUID(int=4),
        payload_version=1,
        form_url=LOGICAL_ORIGIN + "/contact/",
        rest_root=logical_root,
        endpoint=logical_root + suffix,
        form_id=item.form_id,
        captcha_state="NONE",
        dom_fingerprint=item.fingerprint,
        hidden=tuple(InputValue(name=k, value=v) for k, v in item.hidden),
        controls=tuple(controls),
        selections=(Selection(name="consent", checked=True),),
        sender=tuple(
            InputValue(name=k, value=v)
            for k, v in {
                "name": "Lab operator",
                "email": EMAIL,
                "company": "",
                "phone": "",
            }.items()
        ),
        subject="",
        body=MESSAGE,
        name_field="your-name",
        email_field="your-email",
        body_field="your-message",
        field_values=tuple(InputValue(name=k, value=v) for k, v in fields.items()),
    )


def verified_wire(saved, current):
    validate_snapshot(
        saved,
        current,
        expected_hash=digest(saved),
        expected_version=1,
        project_id=UUID(int=1),
        company_id=UUID(int=2),
        source_draft_id=UUID(int=3),
        form_profile_id=UUID(int=4),
    )
    return wire(current)


def decode_wire(content_type, body):
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        + body
    )
    if not message.is_multipart() or message.defects:
        raise ValueError("Malformed multipart")
    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name or name in fields or part.get_filename() or part.defects:
            raise ValueError("Ambiguous multipart")
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            raise TypeError("Non-text multipart")
        fields[name] = payload.decode("utf-8")
    return fields


def local_post(client, observed, content_type, body, origin):
    # Fixed test route, distinct from the candidate's non-executable HTTPS metadata.
    parsed = urlsplit(origin)
    suffix = f"contact-form-7/v1/contact-forms/{observed.form_id}/feedback"
    if (
        os.environ.get("CF7_PROTOCOL_LAB") != "1"
        or parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.netloc != f"127.0.0.1:{parsed.port}"
        or parsed.path
        or parsed.query
        or parsed.fragment
        or observed.endpoint
        not in {
            origin + root + suffix
            for root in ("/wp-json/", "/?rest_route=/", "/index.php?rest_route=/")
        }
        or len(body) > 64000
    ):
        raise ValueError(
            "Only an exact managed loopback fixture route may receive wire"
        )
    return client.post(
        observed.endpoint, content=body, headers={"Content-Type": content_type}
    )


def verify_path(
    client, html, origin, output, report, fixture, check, command, assets, page_url
):
    candidate = make_candidate(html, origin)
    observed = observe(html, origin)
    saved = snapshot(candidate)
    content_type, body = verified_wire(saved, candidate)
    fields = decode_wire(content_type, body)
    report["candidate_contract"] = {
        "version": candidate.contract_version,
        "encoding": candidate.encoding_version,
        "logical_origin_is_placeholder": True,
        "candidate_urls_executed": False,
        "snapshot_sha256": digest(saved),
        "wire_sha256": saved["wire_sha256"],
        "wire_size": saved["wire_size"],
        "form_id": candidate.form_id,
    }
    (output / "candidate-snapshot.json").write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "candidate-wire.bin").write_bytes(body)
    check(
        "candidate wire hash and decoded fields",
        hashlib.sha256(body).hexdigest() == saved["wire_sha256"]
        and fields
        == dict(observed.hidden)
        | {
            "your-name": "Lab operator",
            "your-email": EMAIL,
            "your-message": MESSAGE.replace("\n", "\r\n"),
            "consent": "1",
        },
    )
    captured_mail = None
    for mode, expected in [("capture", "RECEIPT_REPORTED"), ("fail", "UNKNOWN")]:
        fixture("mode", mode)
        before = json.loads(fixture("evidence"))
        report["feedback_post_count"] += 1
        response = local_post(client, observed, content_type, body, origin)
        after = json.loads(fixture("evidence"))
        receipt = classify(
            response.status_code,
            response.headers.get("content-type", ""),
            response.content,
            observed,
        )
        check(
            "candidate actual CF7 " + mode,
            receipt == expected
            and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
            and len(after["submissions"]) == len(before["submissions"]) + 1,
            {
                "http": response.status_code,
                "status": response.json().get("status"),
                "classification": receipt,
                "expected_classification": expected,
                "mail_delta": len(after["mail_calls"]) - len(before["mail_calls"]),
            },
        )
        if mode == "capture":
            captured_mail = after["mail_calls"][-1]
    fixture("mode", "capture")
    before_browser = json.loads(fixture("evidence"))
    browser = json.loads(
        command(
            "node",
            str(assets / "browser_probe.cjs"),
            page_url,
            EMAIL,
            env=os.environ.copy(),
            timeout=90,
        )
    )
    report["feedback_post_count"] += len(browser["posts"])
    after_browser = json.loads(fixture("evidence"))
    check(
        "candidate wire matches actual browser fields and captured mail",
        len(browser["posts"]) == 1
        and dict(browser["posts"][0]["fields"]) == fields
        and browser["posts"][0]["url"] == observed.endpoint
        and classify(
            browser["http_status"],
            "application/json",
            json.dumps(browser["result"]).encode(),
            observed,
        )
        == "RECEIPT_REPORTED"
        and len(after_browser["mail_calls"]) == len(before_browser["mail_calls"]) + 1
        and len(after_browser["submissions"]) == len(before_browser["submissions"]) + 1
        and after_browser["mail_calls"][-1] == captured_mail,
        {
            "fields_equal": dict(browser["posts"][0]["fields"]) == fields,
            "mail_hashes_equal": after_browser["mail_calls"][-1] == captured_mail,
        },
    )
    (output / "candidate-browser-wire.json").write_text(
        json.dumps(browser, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["candidate_mail_evidence"] = captured_mail
    before_revision = json.loads(fixture("evidence"))
    for name, changed in [
        ("consent", html.replace("Lab-only privacy terms", "Changed consent")),
        (
            "unit tag",
            html.replace(observed.unit_tag, observed.unit_tag.replace("-o1", "-o99")),
        ),
    ]:
        try:
            verified_wire(saved, make_candidate(changed, origin))
        except ValueError:
            check("candidate " + name + " revision stopped before HTTP", True)
        else:
            check("candidate " + name + " revision stopped before HTTP", False)
    check(
        "candidate revision performs no extra submission",
        json.loads(fixture("evidence")) == before_revision,
    )


def verify_query(client, html, origin, report, fixture, check):
    candidate = make_candidate(html, origin)
    content_type, body = verified_wire(snapshot(candidate), candidate)
    observed = observe(html, origin)
    fixture("mode", "capture")
    before = json.loads(fixture("evidence"))
    report["feedback_post_count"] += 1
    response = local_post(client, observed, content_type, body, origin)
    after = json.loads(fixture("evidence"))
    check(
        "candidate actual CF7 index query route",
        "/index.php?rest_route=/" in candidate.endpoint
        and classify(
            response.status_code,
            response.headers.get("content-type", ""),
            response.content,
            observed,
        )
        == "RECEIPT_REPORTED"
        and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
        and len(after["submissions"]) == len(before["submissions"]) + 1
        and after["mail_calls"][-1] == report["candidate_mail_evidence"],
    )
