"""Offline fixture mapper rejects uncontrolled forms and stale payloads."""

import os
import unittest
from unittest.mock import patch

import radio_probe as probe
from group_probe import decode_parts, grouped
from test_contract_probe import HTML, ORIGIN

FORM = HTML[HTML.index("<form") :]
RADIO = '<span class="wpcf7-radio"><label><input type="radio" name="topic" value="SNS運用">SNS運用</label><label><input type="radio" name="topic" value="OEM">OEM</label></span>'
PAGE = HTML + FORM * 5 + FORM.replace("</form>", RADIO + "</form>")


class RadioProbeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_one_scalar_part_and_full_fingerprint(self):
        plan, observed = probe.make_radio_candidate(PAGE, ORIGIN, "OEM")
        self.assertEqual(
            grouped(decode_parts(*probe.verified_wire(probe.snapshot(plan), plan)))[
                "topic"
            ],
            ["OEM"],
        )
        self.assertEqual(plan.base.dom_fingerprint, observed.fingerprint)
        self.assertFalse(plan.execution_allowed)

    def test_unknown_disabled_and_real_origin_rejected(self):
        for html, origin, selected in (
            (PAGE, ORIGIN, ""),
            (PAGE, ORIGIN, "UNKNOWN"),
            (PAGE.replace('value="OEM"', 'disabled value="OEM"'), ORIGIN, "OEM"),
            (PAGE, "https://real.example", "OEM"),
            (PAGE.replace('name="topic"', 'name="other"'), ORIGIN, "OEM"),
        ):
            with (
                self.subTest(origin=origin, selected=selected),
                self.assertRaises(ValueError),
            ):
                probe.make_radio_candidate(html, origin, selected)

    def test_revised_and_optout_fail_without_http(self):
        plan, _ = probe.make_radio_candidate(PAGE, ORIGIN, "OEM")
        current, _ = probe.make_radio_candidate(PAGE, ORIGIN, "SNS運用")
        with self.assertRaises(ValueError):
            probe.verified_wire(probe.snapshot(plan), current)
        with (
            patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "0"}),
            self.assertRaises(ValueError),
        ):
            probe.make_radio_candidate(PAGE, ORIGIN, "OEM")
