"""Real CF7 wire cases, separate from Docker lifecycle and application code."""

import json
import os

import httpx
from contract_probe import verify_path, verify_query
from group_probe import verify_groups
from hidden_probe import verify_hidden
from protocol import browser_multipart_value, classify, observe
from radio_probe import verify_radio


def verify(origin, output, report, fixture, check, command, assets, page_url):
    report["httpx_version"] = httpx.__version__
    report["multipart_encoding"] = "lab-browser-crlf-v1"
    report["feedback_post_count"] = 0

    def evidence():
        return json.loads(fixture("evidence"))

    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        page = client.get(page_url)
        check(
            "real rendered DOM",
            page.status_code == 200,
            {"http": page.status_code, "location": page.headers.get("location")},
        )
        (output / "page.html").write_text(page.text, encoding="utf-8")
        observations = [observe(page.text, origin, index) for index in range(4)]
        report["observations"] = [vars(item) for item in observations]
        check("path REST root observed", "/wp-json/" in observations[0].endpoint)

        def submit(
            name,
            index=0,
            overrides=None,
            mode="capture",
            expected="mail_sent",
            expected_http=200,
            encoded=False,
        ):
            fixture("mode", mode)
            item = observations[index]
            fields = dict(item.hidden) | {
                "your-name": "Lab operator",
                "your-email": "operator@example.invalid",
                "your-message": "Lab fixture only 日本語\n第二行",
                "consent": "1",
            }
            for key, value in (overrides or {}).items():
                if value is None:
                    fields.pop(key, None)
                else:
                    fields[key] = value
            before = evidence()
            report["feedback_post_count"] += 1
            response = (
                client.post(item.endpoint, data=fields)
                if encoded
                else client.post(
                    item.endpoint,
                    files=[
                        (key, (None, browser_multipart_value(value)))
                        for key, value in fields.items()
                    ],
                )
            )
            result = response.json()
            observed_status = result.get("status", result.get("code"))
            after = evidence()
            receipt = classify(
                response.status_code,
                response.headers["content-type"],
                response.content,
                item,
            )
            expected_receipt = (
                "RECEIPT_REPORTED"
                if expected == "mail_sent" and index != 3
                else "UNKNOWN"
            )
            detail = {
                "http": response.status_code,
                "status": observed_status,
                "classification": receipt,
                "mail_calls_delta": len(after["mail_calls"])
                - len(before["mail_calls"]),
                "submissions_delta": len(after["submissions"])
                - len(before["submissions"]),
            }
            expected_mail_calls = int(
                (expected == "mail_sent" and mode != "skip" and index != 3)
                or expected == "mail_failed"
            )
            check(
                name,
                response.status_code == expected_http
                and observed_status == expected
                and receipt == expected_receipt
                and detail["mail_calls_delta"] == expected_mail_calls
                and detail["submissions_delta"] == int(expected_http == 200),
                detail,
            )
            return response

        success = submit("multipart standard")
        standard_mail = evidence()["mail_calls"][-1]
        submit(
            "urlencoded rejected",
            encoded=True,
            expected_http=415,
            expected="wpcf7_unsupported_media_type",
        )
        submit(
            "unit tag missing",
            overrides={"_wpcf7_unit_tag": None},
            expected_http=400,
            expected="wpcf7_unit_tag_not_found",
        )
        submit(
            "required field missing",
            overrides={"your-email": ""},
            expected="validation_failed",
        )
        submit(
            "required acceptance missing",
            overrides={"consent": None},
            expected="acceptance_missing",
        )
        submit("optional acceptance omitted", index=1, overrides={"consent": None})
        submit("invert acceptance omitted", index=2, overrides={"consent": None})
        submit(
            "invert acceptance checked rejected",
            index=2,
            expected="acceptance_missing",
        )
        submit("mail capture failure", mode="fail", expected="mail_failed")
        submit("before-mail abort", mode="abort", expected="aborted")
        submit("spam decision", mode="spam", expected="spam")
        submit("skip-mail reports receipt without mail call", mode="skip")
        submit("demo-mode not receipt evidence", index=3)
        fixture("mode", "capture")
        before_browser = evidence()
        browser = json.loads(
            command(
                "node",
                str(assets / "browser_probe.cjs"),
                page_url,
                env=os.environ.copy(),
                timeout=90,
            )
        )
        browser_post = browser["posts"][0]
        report["feedback_post_count"] += len(browser["posts"])
        report["browser_version"] = browser["browser_version"]
        browser_fields = dict(browser_post["fields"])
        after_browser = evidence()
        (output / "browser-wire.json").write_text(
            json.dumps(browser, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report["mail_evidence"] = after_browser
        report["standard_mail"] = standard_mail
        check(
            "browser standard uses matching multipart endpoint",
            browser_post["url"] == observations[0].endpoint
            and browser_post["type"].startswith("multipart/form-data;")
            and dict(observations[0].hidden).items() <= browser_fields.items()
            and browser_fields["your-message"].replace("\r\n", "\n")
            == "Lab fixture only 日本語\n第二行"
            and browser_fields["consent"] == "1"
            and classify(
                browser["http_status"],
                "application/json",
                json.dumps(browser["result"]).encode(),
                observations[0],
            )
            == "RECEIPT_REPORTED"
            and len(after_browser["mail_calls"])
            == len(before_browser["mail_calls"]) + 1
            and len(after_browser["submissions"])
            == len(before_browser["submissions"]) + 1
            and after_browser["mail_calls"][-1] == standard_mail,
            {
                "endpoint": browser_post["url"] == observations[0].endpoint,
                "multipart": browser_post["type"].startswith("multipart/form-data;"),
                "hidden": dict(observations[0].hidden).items()
                <= browser_fields.items(),
                "mail_delta": len(after_browser["mail_calls"])
                - len(before_browser["mail_calls"]),
                "submission_delta": len(after_browser["submissions"])
                - len(before_browser["submissions"]),
                "mail_hash_matches": after_browser["mail_calls"][-1] == standard_mail,
            },
        )
        report["mail_evidence"] = evidence()
        verify_path(
            client,
            page.text,
            origin,
            output,
            report,
            fixture,
            check,
            command,
            assets,
            page_url,
        )
        # Real response mutation checks: zero extra POST for every ambiguous variant.
        good = success.json()
        for name, mutation in [
            ("different form ID", {"contact_form_id": 999999}),
            ("different unit tag", {"into": "#other"}),
            ("demo receipt", {"demo_mode": True}),
            ("custom status", {"status": "fixture_accepted"}),
            ("contradictory validation", {"invalid_fields": [{}]}),
        ]:
            check(
                name + " remains UNKNOWN",
                classify(
                    200,
                    "application/json",
                    json.dumps(good | mutation).encode(),
                    observations[0],
                )
                == "UNKNOWN",
            )
        for name, changed in [
            (
                "consent text",
                page.text.replace("Lab-only privacy terms", "Changed privacy terms"),
            ),
            (
                "unit tag",
                page.text.replace(
                    observations[0].unit_tag,
                    observations[0].unit_tag.replace("-o1", "-o99"),
                ),
            ),
        ]:
            check(
                name + " changes structure evidence",
                observe(changed, origin).fingerprint != observations[0].fingerprint,
            )
        verify_groups(
            client,
            page.text,
            origin,
            output,
            report,
            fixture,
            check,
            command,
            assets,
            page_url,
        )
        verify_radio(
            client,
            page.text,
            origin,
            output,
            report,
            fixture,
            check,
            command,
            assets,
            page_url,
        )
        verify_hidden(
            client,
            page.text,
            origin,
            output,
            report,
            fixture,
            check,
            command,
            assets,
            page_url,
        )
        fixture("query-root")
        query_page = client.get(
            origin + "/?page_id=" + str(report["versions"]["page_id"])
        )
        (output / "query-page.html").write_text(query_page.text, encoding="utf-8")
        check("query-root rendered DOM", query_page.status_code == 200)
        query = observe(query_page.text, origin)
        report["query_observation"] = vars(query)
        check("query REST root observed", "/index.php?rest_route=/" in query.endpoint)
        observations[0] = query
        submit("query-root multipart receipt")
        verify_query(client, query_page.text, origin, report, fixture, check)
        report["mail_evidence"] = evidence()
        check(
            "fixed explicit cases have no extra submission",
            report["feedback_post_count"]
            - report["group_contract"]["feedback_post_count"]
            - report["radio_contract"]["feedback_post_count"]
            - report["extra_hidden_contract"]["feedback_post_count"]
            == 19
            and len(report["mail_evidence"]["submissions"])
            - report["group_contract"]["submission_delta"]
            - report["radio_contract"]["submission_delta"]
            - report["extra_hidden_contract"]["submission_delta"]
            == 17
            and len(report["mail_evidence"]["mail_calls"])
            - report["group_contract"]["mail_capture_delta"]
            - report["radio_contract"]["mail_capture_delta"]
            - report["extra_hidden_contract"]["mail_capture_delta"]
            == report["setup_mail_calls_captured"] + 10,
        )
