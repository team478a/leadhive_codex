import os
import unittest
from unittest.mock import patch

import hidden_probe as probe
from group_probe import decode_parts, grouped
from test_contract_probe import HTML, ORIGIN

FORM = HTML[HTML.index("<form") :]
EXTRA = (
    '<input type="hidden" name="leadhive_lab_context" value="fixture-business-context">'
)
PAGE = HTML + FORM * 6 + FORM.replace("</form>", EXTRA + "</form>")


class HiddenProbeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_fixed_value_and_full_fingerprint(self):
        plan, observed = probe.make_hidden_candidate(PAGE, ORIGIN)
        fields = grouped(decode_parts(*probe.verified_wire(probe.snapshot(plan), plan)))
        self.assertEqual(fields[probe.NAME], [probe.VALUE])
        self.assertEqual(plan.base.dom_fingerprint, observed.fingerprint)
        self.assertFalse(plan.execution_allowed)

    def test_unknown_duplicate_disabled_remote_and_optout_rejected(self):
        for html, origin in (
            (PAGE.replace(probe.VALUE, "changed"), ORIGIN),
            (PAGE.replace(EXTRA, EXTRA * 2), ORIGIN),
            (
                PAGE.replace(EXTRA, EXTRA.replace('type="hidden"', 'type="text"')),
                ORIGIN,
            ),
            (PAGE.replace(EXTRA, EXTRA.replace("<input", "<input disabled")), ORIGIN),
            (PAGE, "https://real.example"),
            (HTML, ORIGIN),
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                probe.make_hidden_candidate(html, origin)
        with (
            patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "0"}),
            self.assertRaises(ValueError),
        ):
            probe.make_hidden_candidate(PAGE, ORIGIN)

    def test_changed_dom_invalidates_saved_snapshot(self):
        plan, _ = probe.make_hidden_candidate(PAGE, ORIGIN)
        current, _ = probe.make_hidden_candidate(
            PAGE.replace(EXTRA, EXTRA + "<span>revision</span>"), ORIGIN
        )
        with self.assertRaises(ValueError):
            probe.verified_wire(probe.snapshot(plan), current)
