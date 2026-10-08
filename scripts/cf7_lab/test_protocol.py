"""Offline negative cases for the lab verifier. No Docker, database or HTTP."""

import json
import unittest
from unittest.mock import patch

from protocol import browser_multipart_value, classify, observe

ORIGIN = "http://127.0.0.1:19876"
HTML = """<script>var wpcf7 = {"api": {"root": "http://127.0.0.1:19876/wp-json/",
"namespace": "contact-form-7/v1"}};</script>
<form method="post" action="/contact/#wpcf7-f7-p12-o1" class="wpcf7-form">
<input type="hidden" name="_wpcf7" value="7">
<input type="hidden" name="_wpcf7_version" value="6.1.4">
<input type="hidden" name="_wpcf7_locale" value="en_US">
<input type="hidden" name="_wpcf7_unit_tag" value="wpcf7-f7-p12-o1">
<input type="hidden" name="_wpcf7_container_post" value="12">
<input type="hidden" name="_wpcf7_posted_data_hash" value="">
<label>Name<input name="your-name" type="text" required></label>
<label>Terms<input name="consent" type="checkbox" value="1"></label>
<textarea name="your-message"></textarea><input type="submit" value="Send"></form>"""
GOOD = {
    "contact_form_id": 7,
    "status": "mail_sent",
    "message": "Lab receipt",
    "into": "#wpcf7-f7-p12-o1",
    "invalid_fields": [],
    "posted_data_hash": "lab-hash",
}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.observed = observe(HTML, ORIGIN)

    def test_browser_multipart_newlines_preserve_text_and_are_idempotent(self):
        for value in ("日本語\n第二行", "日本語\r第二行", "日本語\r\n第二行"):
            encoded = browser_multipart_value(value)
            self.assertEqual(encoded, "日本語\r\n第二行")
            self.assertEqual(browser_multipart_value(encoded), encoded)
        self.assertEqual(
            browser_multipart_value("  Untrimmed 日本語  "), "  Untrimmed 日本語  "
        )

    def test_explicit_opt_in_before_any_acquisition_or_docker(self):
        import run

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(run, "source") as source,
            patch.object(run, "docker") as docker,
        ):
            with self.assertRaisesRegex(RuntimeError, "CF7_PROTOCOL_LAB"):
                run.run()
            source.assert_not_called()
            docker.assert_not_called()

    def test_path_and_query_are_observed_without_evaluating_script(self):
        self.assertEqual(self.observed.form_id, 7)
        self.assertEqual(
            self.observed.endpoint,
            ORIGIN + "/wp-json/contact-form-7/v1/contact-forms/7/feedback",
        )
        query = observe(HTML.replace("/wp-json/", "/?rest_route=/"), ORIGIN)
        self.assertIn("/?rest_route=/contact-form-7/v1/", query.endpoint)
        self.assertNotEqual(query.fingerprint, self.observed.fingerprint)
        index_query = observe(
            HTML.replace("/wp-json/", "/index.php?rest_route=/"), ORIGIN
        )
        self.assertIn("/index.php?rest_route=/contact-form-7/v1/", index_query.endpoint)

    def test_only_exact_loopback_lab_origin(self):
        for origin in (
            "https://company.example",
            "http://localhost:19876",
            ORIGIN + "/",
            "http://user@127.0.0.1:19876",
            ORIGIN + "?redirect=x",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                observe(HTML, origin)

    def test_unknown_tokens_namespaces_and_controls_stop(self):
        for changed in (
            HTML.replace(
                "</form>", '<input type="hidden" name="_wpnonce" value="secret"></form>'
            ),
            HTML.replace(
                "</form>", '<input type="hidden" name="tracking-token"></form>'
            ),
            HTML.replace(
                'name="_wpcf7_posted_data_hash" value=""',
                'name="_wpcf7_posted_data_hash" value="previous"',
            ),
            HTML.replace('value="6.1.4"', 'value="6.1.5"'),
            HTML.replace("contact-form-7/v1", "custom/v1"),
            HTML.replace(ORIGIN + "/wp-json/", "https://evil.example/wp-json/"),
            HTML.replace('type="text"', 'type="file"'),
            HTML.replace('type="text"', 'type="password"'),
            HTML.replace("</form>", '<input name="your-name"></form>'),
            HTML.replace("<form ", '<form onsubmit="custom()" '),
            HTML + '<script src="https://captcha.example"></script>',
            HTML.replace("wpcf7-f7-p12-o1", "wpcf7-f8-p12-o1"),
            HTML + '<script>var wpcf7 = {"api":{}};</script>',
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                observe(changed, ORIGIN)

    def test_consent_and_payload_structure_change_fingerprint(self):
        for changed in (
            HTML.replace("Terms", "New terms"),
            HTML.replace("required", ""),
            HTML.replace("your-message", "different-message"),
            HTML.replace('type="checkbox"', 'type="checkbox" class="invert"'),
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    observe(changed, ORIGIN).fingerprint, self.observed.fingerprint
                )

    def test_exact_receipt_not_delivery_proof(self):
        self.assertEqual(
            classify(
                200,
                "application/json; charset=UTF-8",
                json.dumps(GOOD).encode(),
                self.observed,
            ),
            "RECEIPT_REPORTED",
        )

    def test_mismatches_and_failure_status_remain_unknown(self):
        for changed in (
            {"contact_form_id": True},
            {"contact_form_id": "7"},
            {"contact_form_id": 8},
            {"into": "#another"},
            {"demo_mode": True},
            {"demo_mode": 0},
            {"invalid_fields": [{}]},
            {"message": None},
            {"posted_data_hash": ""},
            {"posted_data_hash": None},
            {"extra_plugin": True},
        ):
            with self.subTest(changed=changed):
                self.assertEqual(
                    classify(
                        200,
                        "application/json",
                        json.dumps(GOOD | changed).encode(),
                        self.observed,
                    ),
                    "UNKNOWN",
                )
        for status in (
            "validation_failed",
            "acceptance_missing",
            "spam",
            "aborted",
            "mail_failed",
            "error",
            "fixture_accepted",
            "success",
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    classify(
                        200,
                        "application/json",
                        json.dumps(GOOD | {"status": status}).encode(),
                        self.observed,
                    ),
                    "UNKNOWN",
                )

    def test_missing_required_response_evidence(self):
        for name in GOOD:
            data = {key: value for key, value in GOOD.items() if key != name}
            with self.subTest(name=name):
                self.assertEqual(
                    classify(
                        200,
                        "application/json",
                        json.dumps(data).encode(),
                        self.observed,
                    ),
                    "UNKNOWN",
                )

    def test_ambiguous_wire_is_never_receipt(self):
        for body in (
            b"{}",
            b"null",
            b"[]",
            b'"mail_sent"',
            b"\xff",
            b'{"status":"error","status":"mail_sent"}',
            b"{" + b"x" * 64000,
            b"<html>Thank you</html>",
            b'{"status":',
        ):
            with self.subTest(body=body[:30]):
                self.assertEqual(
                    classify(200, "application/json", body, self.observed), "UNKNOWN"
                )
        for status in (201, 204, 301, 302, 307, 308, 400, 500):
            with self.subTest(status=status):
                self.assertEqual(
                    classify(
                        status,
                        "application/json",
                        json.dumps(GOOD).encode(),
                        self.observed,
                    ),
                    "UNKNOWN",
                )
        self.assertEqual(
            classify(200, "text/html", json.dumps(GOOD).encode(), self.observed),
            "UNKNOWN",
        )


if __name__ == "__main__":
    unittest.main()
