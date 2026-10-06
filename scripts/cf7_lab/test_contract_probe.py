"""Offline bridge boundaries. No Docker, real DNS, HTTP or DB."""

import os
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import contract_probe as probe
from protocol import observe

ORIGIN = "http://127.0.0.1:19876"
HTML = """<script>var wpcf7 = {"api":{"root":"http://127.0.0.1:19876/wp-json/",
"namespace":"contact-form-7/v1"}};</script>
<form class="wpcf7-form" method="post" action="/contact/">
<input type="hidden" name="_wpcf7" value="7">
<input type="hidden" name="_wpcf7_version" value="6.1.4">
<input type="hidden" name="_wpcf7_locale" value="en_US">
<input type="hidden" name="_wpcf7_unit_tag" value="wpcf7-f7-p12-o1">
<input type="hidden" name="_wpcf7_container_post" value="12">
<input type="hidden" name="_wpcf7_posted_data_hash" value="">
<label>Name<input name="your-name" type="text" required></label>
<label>Email<input name="your-email" type="email" required></label>
<label>Message<textarea name="your-message" required></textarea></label>
<span class="wpcf7-acceptance"><label>Lab-only privacy terms
<input name="consent" type="checkbox" value="1"></label></span></form>"""


class ContractProbeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_prepared_wire_decodes_to_exact_values_and_known_logical_url(self):
        candidate = probe.make_candidate(HTML, ORIGIN)
        content_type, body = probe.verified_wire(probe.snapshot(candidate), candidate)
        fields = probe.decode_wire(content_type, body)
        self.assertEqual(fields["your-message"], "Lab fixture only 日本語\r\n第二行")
        self.assertEqual(fields["your-email"], probe.EMAIL)
        self.assertEqual(len(fields), 10)
        self.assertTrue(
            candidate.endpoint.startswith(probe.LOGICAL_ORIGIN + "/wp-json/")
        )

    def test_unknown_variant_fields_and_captcha_are_not_prepared(self):
        for html in [
            HTML.replace('class="wpcf7-acceptance"', 'class="wpcf7-acceptance invert"'),
            HTML.replace(
                'class="wpcf7-acceptance"', 'class="wpcf7-acceptance optional"'
            ),
            HTML.replace('name="your-name"', 'name="other-name"'),
            HTML + "captcha",
        ]:
            with self.subTest(html=html[:30]), self.assertRaises(ValueError):
                probe.make_candidate(html, ORIGIN)

    def test_revision_rejected_before_local_post(self):
        candidate = probe.make_candidate(HTML, ORIGIN)
        saved = probe.snapshot(candidate)
        revised = probe.make_candidate(
            HTML.replace("Lab-only privacy terms", "New terms"), ORIGIN
        )
        with patch.object(probe, "local_post") as post, self.assertRaises(ValueError):
            probe.verified_wire(saved, revised)
        post.assert_not_called()

    def test_only_exact_local_feedback_can_receive_wire(self):
        observed = observe(HTML, ORIGIN)
        client = Mock()
        probe.local_post(client, observed, "multipart/form-data", b"fake", ORIGIN)
        self.assertEqual(client.post.call_count, 1)
        client.reset_mock()
        for origin, endpoint in [
            (ORIGIN, "https://company.example/feedback"),
            (ORIGIN, observed.endpoint + "?extra=1"),
            ("http://u:p@127.0.0.1:19876", observed.endpoint),
            ("https://127.0.0.1:19876", observed.endpoint),
        ]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                probe.local_post(
                    client,
                    replace(observed, endpoint=endpoint),
                    "multipart/form-data",
                    b"fake",
                    origin,
                )
        client.post.assert_not_called()

    def test_flag_off_precedes_observation_and_http(self):
        with (
            patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "0"}),
            patch.object(probe, "observe") as observer,
        ):
            with self.assertRaises(ValueError):
                probe.make_candidate(HTML, ORIGIN)
            observer.assert_not_called()
            client = Mock()
            with self.assertRaises(ValueError):
                probe.local_post(
                    client,
                    observe(HTML, ORIGIN),
                    "multipart/form-data",
                    b"fake",
                    ORIGIN,
                )
            client.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
