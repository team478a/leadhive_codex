"""6.2 compatibility measurements only; no production candidate or dispatch."""

import copy
import json
import os

import httpx
from bs4 import BeautifulSoup
from contract_probe import EMAIL, MESSAGE, local_post, make_candidate
from protocol import browser_multipart_value, classify, observe


def fixture_wire(html, origin, *, mixed=False):
    if os.environ.get("CF7_PROTOCOL_LAB") != "1":
        raise ValueError("Explicit lab opt-in required")
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.select("form.wpcf7-form")
    if len(forms) != 9:
        raise ValueError("Fixed nine-form fixture required")
    form = forms[8 if mixed else 0]
    fields = list(form.select("input[name], textarea[name], select[name]"))
    clean = copy.deepcopy(soup)
    target = clean.select("form.wpcf7-form")[8 if mixed else 0]
    if mixed:
        for selector in (
            ".wpcf7-checkbox",
            ".wpcf7-radio",
            '[name="leadhive_lab_context"]',
        ):
            for field in target.select(selector):
                field.decompose()
    for other in clean.select("form.wpcf7-form"):
        if other is not target:
            other.decompose()
    observed = observe(str(clean), origin, plugin_version="6.2")
    expected = dict(observed.hidden) | {
        "your-name": "Lab operator",
        "your-email": EMAIL,
        "your-message": MESSAGE,
        "consent": "1",
    }
    types = {
        "your-name": "text",
        "your-email": "email",
        "your-message": "textarea",
        "consent": "checkbox",
    }
    if mixed:
        expected |= {
            "services[]": "",
            "topic": "",
            "leadhive_lab_context": "fixture-business-context",
        }
        types |= {
            "services[]": "checkbox",
            "topic": "radio",
            "leadhive_lab_context": "hidden",
        }
    counts: dict[str, int] = {}
    pairs = []
    for field in fields:
        name = str(field.get("name"))
        kind = "textarea" if field.name == "textarea" else field.get("type")
        if (
            name not in expected
            or kind != types.get(name, "hidden")
            or field.has_attr("disabled")
        ):
            raise ValueError("Unknown or disabled fixed fixture control")
        counts[name] = counts.get(name, 0) + 1
        if name in ("services[]", "topic"):
            options = (
                ("SNS運用", "Website", "OEM")
                if name == "services[]"
                else ("SNS運用", "OEM")
            )
            if (
                counts[name] > len(options)
                or field.get("value") != options[counts[name] - 1]
            ):
                raise ValueError("Unknown fixture option")
            if field.get("value") not in (
                ("SNS運用", "OEM") if name == "services[]" else ("OEM",)
            ):
                continue
            value = str(field.get("value"))
        else:
            value = expected[name]
            if kind == "hidden" and field.get("value", "") != value:
                raise ValueError("Hidden value mismatch")
        pairs.append((name, browser_multipart_value(value)))
    if counts != {
        name: 3 if name == "services[]" else 2 if name == "topic" else 1
        for name in expected
    }:
        raise ValueError("Missing or duplicate control")
    return observed, pairs


def verify_version(origin, output, report, fixture, check, command, assets, page_url):
    report["feedback_post_count"] = 0
    records = []
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        page = client.get(page_url)
        check("6.2 rendered DOM", page.status_code == 200)
        (output / "page.html").write_text(page.text, encoding="utf-8")
        standard, pairs = fixture_wire(page.text, origin)
        mixed, mixed_pairs = fixture_wire(page.text, origin, mixed=True)
        try:
            make_candidate(page.text, origin)
        except ValueError:
            denied = True
        else:
            denied = False
        check("6.1.4 candidate refuses 6.2 before HTTP", denied)

        def submit(
            name,
            item,
            fields,
            *,
            mode="capture",
            expected=("mail_sent",),
            http=200,
            encoded=False,
        ):
            fixture("mode", mode)
            before = json.loads(fixture("evidence"))
            request = (
                httpx.Request("POST", item.endpoint, data=dict(fields))
                if encoded
                else httpx.Request(
                    "POST", item.endpoint, files=[(n, (None, v)) for n, v in fields]
                )
            )
            report["feedback_post_count"] += 1
            response = local_post(
                client, item, request.headers["content-type"], request.read(), origin
            )
            result = response.json()
            status = result.get("status", result.get("code"))
            after = json.loads(fixture("evidence"))
            delta = len(after["mail_calls"]) - len(before["mail_calls"])
            receipt = classify(
                response.status_code,
                response.headers.get("content-type", ""),
                response.content,
                item,
            )
            detail = {
                "case": name,
                "http": response.status_code,
                "status": status,
                "classification": receipt,
                "response_keys": sorted(result),
                "mail_capture_delta": delta,
                "submission_delta": len(after["submissions"])
                - len(before["submissions"]),
            }
            records.append(detail)
            check(
                "6.2 " + name,
                response.status_code == http
                and status in expected
                and delta
                == int(status in ("mail_sent", "mail_failed") and mode != "skip")
                and (status == "mail_sent" or receipt == "UNKNOWN"),
                detail,
            )
            return after["mail_calls"][-1] if delta else None

        submit("standard", standard, pairs)
        submit(
            "urlencoded",
            standard,
            pairs,
            expected=("wpcf7_unsupported_media_type",),
            http=415,
            encoded=True,
        )
        submit(
            "missing unit",
            standard,
            [(n, v) for n, v in pairs if n != "_wpcf7_unit_tag"],
            expected=("wpcf7_unit_tag_not_found",),
            http=400,
        )
        for name in ("your-name", "consent"):
            submit(
                "missing " + name,
                standard,
                [(n, v) for n, v in pairs if n != name],
                expected=(
                    "acceptance_missing" if name == "consent" else "validation_failed",
                ),
            )
        for mode, status in (
            ("fail", "mail_failed"),
            ("spam", "spam"),
            ("abort", "aborted"),
            ("skip", "mail_sent"),
        ):
            submit(mode, standard, pairs, mode=mode, expected=(status,))
        captured = submit("mixed", mixed, mixed_pairs)
        submit("mixed fail", mixed, mixed_pairs, mode="fail", expected=("mail_failed",))
        for name in ("services[]", "topic"):
            submit(
                "missing " + name,
                mixed,
                [(n, v) for n, v in mixed_pairs if n != name],
                expected=("validation_failed",),
            )
        submit(
            "changed hidden negative",
            mixed,
            [
                (n, "OTHER_FIXTURE_CONTEXT" if n == "leadhive_lab_context" else v)
                for n, v in mixed_pairs
            ],
            expected=("mail_sent", "validation_failed"),
        )
        submit(
            "duplicate radio negative",
            mixed,
            [(n, v) for n, v in mixed_pairs if n != "topic"]
            + [("topic", "SNS運用"), ("topic", "OEM")],
            expected=("mail_sent", "validation_failed"),
        )
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
            and [tuple(p) for p in browser["posts"][0]["fields"]] == mixed_pairs
        )
        check(
            "6.2 browser full order and captured mail",
            equal
            and browser["posts"][0]["url"] == mixed.endpoint
            and len(after["mail_calls"]) == len(before["mail_calls"]) + 1
            and after["mail_calls"][-1] == captured,
        )
        (output / "version-browser-wire.json").write_text(
            json.dumps(browser, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        fixture("query-root")
        query_page = client.get(
            origin + "/?page_id=" + str(report["versions"]["page_id"])
        )
        query, query_pairs = fixture_wire(query_page.text, origin)
        check("6.2 query root", "/index.php?rest_route=/" in query.endpoint)
        submit("query root", query, query_pairs)
    report["version_comparison"] = {
        "plugin_version": "6.2",
        "hidden_names": [n for n, _ in standard.hidden],
        "old_candidate_rejected": denied,
        "cases": records,
        "browser_full_part_order_equal": equal,
        "part_count": len(mixed_pairs),
        "feedback_post_count": report["feedback_post_count"],
        "candidate_contract_added": False,
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
