import os
import unittest
from unittest.mock import patch

import ordered_probe as probe
from group_probe import decode_parts
from test_contract_probe import ORIGIN
from test_group_probe import GROUP
from test_mixed_probe import PAGE


class OrderedProbeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_dom_order_and_unchecked_exclusion(self):
        plan, _ = probe.make_ordered_candidate(PAGE, ORIGIN)
        parts = decode_parts(*probe.verified_wire(probe.snapshot(plan), plan))
        names = [name for name, _ in parts]
        self.assertEqual(
            names[-5:],
            ["consent", "services[]", "services[]", "topic", "leadhive_lab_context"],
        )
        self.assertNotIn(("services[]", "Website"), parts)

    def test_order_revision_and_unknown_control_rejected(self):
        plan, _ = probe.make_ordered_candidate(PAGE, ORIGIN)
        current, _ = probe.make_ordered_candidate(
            PAGE.replace(GROUP, "").replace("</form>", GROUP + "</form>"), ORIGIN
        )
        with self.assertRaises(ValueError):
            probe.verified_wire(probe.snapshot(plan), current)
        with self.assertRaises(ValueError):
            probe.make_ordered_candidate(
                PAGE.replace('name="topic"', 'name="foreign"'), ORIGIN
            )

    def test_remote_and_optout_rejected(self):
        with self.assertRaises(ValueError):
            probe.make_ordered_candidate(PAGE, "https://real.example")
        with (
            patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "0"}),
            self.assertRaises(ValueError),
        ):
            probe.make_ordered_candidate(PAGE, ORIGIN)
