import os
import unittest
from unittest.mock import patch

import mixed_probe as probe
from group_probe import decode_parts, grouped
from test_contract_probe import HTML, ORIGIN
from test_group_probe import GROUP
from test_hidden_probe import EXTRA
from test_radio_probe import RADIO

FORM = HTML[HTML.index("<form") :]
PAGE = HTML + FORM * 7 + FORM.replace("</form>", GROUP + RADIO + EXTRA + "</form>")


class MixedProbeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_all_values_and_full_fingerprint(self):
        plan, observed = probe.make_mixed_candidate(PAGE, ORIGIN)
        fields = grouped(decode_parts(*probe.verified_wire(probe.snapshot(plan), plan)))
        self.assertEqual(fields["services[]"], ["SNS運用", "OEM"])
        self.assertEqual(fields["topic"], ["OEM"])
        self.assertEqual(fields["leadhive_lab_context"], ["fixture-business-context"])
        self.assertEqual(plan.groups.base.dom_fingerprint, observed.fingerprint)
        self.assertEqual(plan.groups.base, plan.radio.base)

    def test_unknown_or_missing_components_and_remote_rejected(self):
        for html, origin in (
            (PAGE.replace(EXTRA, ""), ORIGIN),
            (PAGE.replace(RADIO, ""), ORIGIN),
            (PAGE.replace(GROUP, ""), ORIGIN),
            (PAGE.replace("fixture-business-context", "changed"), ORIGIN),
            (PAGE, "https://real.example"),
            (HTML, ORIGIN),
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                probe.make_mixed_candidate(html, origin)

    def test_dom_revision_and_optout_rejected(self):
        plan, _ = probe.make_mixed_candidate(PAGE, ORIGIN)
        current, _ = probe.make_mixed_candidate(
            PAGE.replace(EXTRA, EXTRA + "<span>revision</span>"), ORIGIN
        )
        with self.assertRaises(ValueError):
            probe.verified_wire(probe.snapshot(plan), current)
        with (
            patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "0"}),
            self.assertRaises(ValueError),
        ):
            probe.make_mixed_candidate(PAGE, ORIGIN)
