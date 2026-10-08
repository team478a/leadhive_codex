"""Explicit 6.2 lab bridge. Contracts never supply an executable destination."""

import hashlib
import json
from dataclasses import replace
from uuid import UUID

from app.services.cf7_62_contract import CF762Candidate, snapshot, values, wire
from app.services.cf7_candidate_contract import digest
from bs4 import BeautifulSoup
from contract_probe import EMAIL, MESSAGE
from protocol import browser_multipart_value
from version_probe import fixture_wire


def make_candidate_62(html, origin, *, mixed=True):
    observed, pairs = fixture_wire(html, origin, mixed=mixed)
    form = BeautifulSoup(html, "html.parser").select("form.wpcf7-form")[
        8 if mixed else 0
    ]
    acceptance = form.select_one(".wpcf7-acceptance")
    classes = acceptance.get("class") if acceptance else None
    consent = form.select_one('[name="consent"]')
    if (
        not isinstance(classes, list)
        or {"optional", "invert"} & set(classes)
        or consent is None
        or consent.get("value") != "1"
        or form.select("[onclick], [onsubmit], [formaction], [formmethod]")
    ):
        raise ValueError("Standard acceptance required")
    fingerprint = hashlib.sha256(str(form).encode()).hexdigest()
    logical = "https://managed.example"
    base = {
        "project_id": UUID(int=1),
        "company_id": UUID(int=2),
        "source_draft_id": UUID(int=3),
        "form_profile_id": UUID(int=4),
        "payload_version": 1,
        "form_url": logical + "/contact/",
        "rest_root": logical + "/wp-json/",
        "endpoint": logical
        + f"/wp-json/contact-form-7/v1/contact-forms/{observed.form_id}/feedback",
        "form_id": observed.form_id,
        "captcha_state": "NONE",
        "dom_fingerprint": fingerprint,
        "hidden": [{"name": n, "value": v} for n, v in observed.hidden],
        "controls": [
            {
                "name": n,
                "kind": kind,
                "required": True,
                "label": "Lab consent" if kind == "checkbox" else "",
                "checkbox_value": "1" if kind == "checkbox" else "",
            }
            for n, kind in (
                ("your-name", "text"),
                ("your-email", "email"),
                ("your-message", "textarea"),
                ("consent", "checkbox"),
            )
        ],
        "selections": [{"name": "consent", "checked": True}],
        "sender": [
            {"name": n, "value": v}
            for n, v in (
                ("name", "Lab operator"),
                ("email", EMAIL),
                ("company", ""),
                ("phone", ""),
            )
        ],
        "subject": "",
        "body": MESSAGE,
        "name_field": "your-name",
        "email_field": "your-email",
        "body_field": "your-message",
        "field_values": [
            {"name": n, "value": v}
            for n, v in (
                ("your-name", "Lab operator"),
                ("your-email", EMAIL),
                ("your-message", MESSAGE),
                ("consent", "1"),
            )
        ],
    }

    def group(name, items, chosen):
        fields = form.find_all("input", attrs={"name": name})
        for field, value in zip(fields, items, strict=True):
            label = field.find_parent("label")
            if label is None or label.get_text(strip=True) != value:
                raise ValueError("Fixed option meaning required")
        return {
            "group_id": name.removesuffix("[]"),
            "name": name,
            "label": "Fixed lab business choice",
            "purpose": "BUSINESS_SELECTION",
            "required": True,
            "min_selected": 1,
            "max_selected": 1 if name == "topic" else 3,
            "options": [
                {
                    "option_id": f"option{i}",
                    "label": v,
                    "value": v,
                    "initially_checked": fields[i].has_attr("checked"),
                }
                for i, v in enumerate(items)
            ],
            "choices": [
                {"option_id": f"option{i}", "checked": v in chosen}
                for i, v in enumerate(items)
            ],
        }

    groups = (
        [group("services[]", ("SNS運用", "Website", "OEM"), ("SNS運用", "OEM"))]
        if mixed
        else []
    )
    radio = group("topic", ("SNS運用", "OEM"), ("OEM",)) if mixed else None
    extra = (
        {
            "name": "leadhive_lab_context",
            "value": "fixture-business-context",
            "purpose": "FIXED_LAB_ROUTING_CONTEXT",
        }
        if mixed
        else None
    )
    refs = []
    for name, value in pairs:
        kind, option = "BASE_FIELD", ""
        if name.startswith("_wpcf7"):
            kind = "BASE_HIDDEN"
        elif name == "leadhive_lab_context":
            kind = "EXTRA_HIDDEN"
        elif name in ("services[]", "topic"):
            kind = "CHECKBOX" if name == "services[]" else "RADIO"
            options = (
                ("SNS運用", "Website", "OEM")
                if kind == "CHECKBOX"
                else ("SNS運用", "OEM")
            )
            option = f"option{options.index(value)}"
        refs.append({"kind": kind, "name": name, "option_id": option})
    plan = CF762Candidate.model_validate_json(
        json.dumps(
            {
                "source_kind": "CONTROLLED_FIXTURE",
                "base": base,
                "groups": groups,
                "radio": radio,
                "extra": extra,
                "order": refs,
            },
            default=str,
        )
    )
    lookup = values(plan)
    if [
        (r.name, browser_multipart_value(lookup[(r.kind, r.name, r.option_id)]))
        for r in plan.order
    ] != pairs:
        raise ValueError("DOM and contract values disagree")
    return plan, replace(observed, fingerprint=fingerprint)


def verify_contract_62(client, html, origin, report, fixture, check):
    import json

    from app.services.cf7_62_contract import validate_snapshot
    from contract_probe import local_post
    from protocol import classify

    plan, observed = make_candidate_62(html, origin)
    saved = snapshot(plan)
    binding = {
        "expected_hash": digest(saved),
        "expected_version": 1,
        "project_id": plan.base.project_id,
        "company_id": plan.base.company_id,
        "source_draft_id": plan.base.source_draft_id,
        "form_profile_id": plan.base.form_profile_id,
    }
    validate_snapshot(saved, plan, **binding)
    checks = 0
    for name, changed in (
        ("order", plan.model_copy(update={"order": tuple(reversed(plan.order))})),
        (
            "DOM",
            plan.model_copy(
                update={
                    "base": plan.base.model_copy(update={"dom_fingerprint": "0" * 64})
                }
            ),
        ),
        (
            "version",
            plan.model_copy(
                update={
                    "base": plan.base.model_copy(update={"plugin_version": "6.1.4"})
                }
            ),
        ),
        ("authority", plan.model_copy(update={"execution_allowed": True})),
    ):
        try:
            validate_snapshot(saved, changed, **binding)
        except ValueError:
            checks += 1
        check("6.2 contract refuses " + name + " before HTTP", checks > 0)
        checks = 0
    kind, body = wire(plan)
    statuses = []
    for mode in ("capture", "fail"):
        fixture("mode", mode)
        before = json.loads(fixture("evidence"))
        report["feedback_post_count"] += 1
        response = local_post(client, observed, kind, body, origin)
        after = json.loads(fixture("evidence"))
        result = classify(
            response.status_code,
            response.headers.get("content-type", ""),
            response.content,
            observed,
        )
        status = response.json().get("status")
        check(
            "6.2 contract wire " + mode,
            status == ("mail_sent" if mode == "capture" else "mail_failed")
            and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
            and result == ("RECEIPT_REPORTED" if mode == "capture" else "UNKNOWN"),
        )
        statuses.append(status)
    report["candidate_62_contract"] = {
        "contract_hash": saved["contract_hash"],
        "wire_sha256": saved["wire_sha256"],
        "part_count": len(plan.order),
        "statuses": statuses,
        "execution_allowed": False,
        "eligible_for_approval": False,
        "feedback_post_count": 2,
    }
