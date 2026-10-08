import json
import os
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from contract_probe import make_candidate
from profiles import get_profile
from protocol import classify, observe
from test_contract_probe import HTML, ORIGIN
from test_mixed_probe import PAGE
from version_probe import fixture_wire

PAGE62 = PAGE.replace('value="6.1.4"', 'value="6.2"')
HTML62 = HTML.replace('value="6.1.4"', 'value="6.2"')


class VersionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_explicit_profile_does_not_weaken_default_observer_or_candidate(self):
        self.assertEqual(
            dict(observe(HTML62, ORIGIN, plugin_version="6.2").hidden)[
                "_wpcf7_version"
            ],
            "6.2",
        )
        for action in (
            lambda: observe(HTML62, ORIGIN),
            lambda: observe(HTML, ORIGIN, plugin_version="6.2"),
            lambda: observe(HTML62, ORIGIN, plugin_version="6.3"),
            lambda: make_candidate(HTML62, ORIGIN),
        ):
            with self.assertRaises(ValueError):
                action()

    def test_mixed_fixed_values_dom_order_and_unchecked(self):
        observed, fields = fixture_wire(PAGE62, ORIGIN, mixed=True)
        self.assertEqual(dict(observed.hidden)["_wpcf7_version"], "6.2")
        self.assertEqual(
            fields[-4:],
            [
                ("services[]", "SNS運用"),
                ("services[]", "OEM"),
                ("topic", "OEM"),
                ("leadhive_lab_context", "fixture-business-context"),
            ],
        )
        self.assertNotIn(("services[]", "Website"), fields)
        self.assertEqual(len(fields), 14)

    def test_unknown_duplicate_disabled_and_remote_rejected(self):
        for html, origin in (
            (PAGE62.replace('name="topic"', 'name="foreign"'), ORIGIN),
            (PAGE62.replace('value="OEM"', 'value="foreign"'), ORIGIN),
            (PAGE62.replace("fixture-business-context", "secret"), ORIGIN),
            (PAGE62.replace('name="your-name"', 'disabled name="your-name"'), ORIGIN),
            (PAGE62, "https://real.example"),
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                fixture_wire(html, origin, mixed=True)
        with (
            patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "0"}),
            self.assertRaises(ValueError),
        ):
            fixture_wire(PAGE62, ORIGIN)

    def test_profiles_are_pinned_and_unknown_denied(self):
        old = get_profile("6.1.4")
        self.assertEqual(old.commit, "165278e868387ec393569ecd2dbfda37e8b5b950")
        self.assertEqual(get_profile("6.2").wp_image, "wordpress:7.1.2-php8.3-apache")
        with self.assertRaises(ValueError):
            get_profile("latest")
        with self.assertRaises(FrozenInstanceError):
            old.version = "6.2"

    def test_62_acceptance_missing_is_unknown_not_receipt(self):
        observed = observe(HTML62, ORIGIN, plugin_version="6.2")
        body = json.dumps(
            {
                "contact_form_id": observed.form_id,
                "into": "#" + observed.unit_tag,
                "status": "acceptance_missing",
                "message": "Lab terms missing",
                "invalid_fields": [],
                "posted_data_hash": "",
            }
        ).encode()
        self.assertEqual(classify(200, "application/json", body, observed), "UNKNOWN")
