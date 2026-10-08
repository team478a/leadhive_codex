"""Offline fixed-group bridge boundaries. No Docker or external requests."""

import os
import unittest
from unittest.mock import patch

import group_probe as probe
from test_contract_probe import HTML, ORIGIN

GROUP = (
    '<span class="wpcf7-checkbox">'
    + "".join(
        f'<label><input type="checkbox" name="services[]" value="{value}">{value}</label>'
        for value in probe.VALUES
    )
    + "</span>"
)
FORM = HTML[HTML.index("<form") :]
GROUP_PAGE = HTML + FORM * 3 + FORM.replace("</form>", GROUP + "</form>") * 2


class GroupProbeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_repeated_names_survive_decode_and_placeholder_is_never_executed(self):
        plan, observed = probe.make_group_candidate(
            GROUP_PAGE,
            ORIGIN,
            4,
            required=True,
            selected=(probe.VALUES[0], probe.VALUES[2]),
        )
        content_type, body = probe.verified_wire(probe.snapshot(plan), plan)
        parts = probe.decode_parts(content_type, body)
        self.assertEqual(
            probe.grouped(parts)["services[]"], [probe.VALUES[0], probe.VALUES[2]]
        )
        self.assertTrue(observed.endpoint.startswith(ORIGIN + "/wp-json/"))
        self.assertEqual(plan.base.form_url, "https://managed.example/contact/")
        self.assertFalse(plan.execution_allowed)

    def test_optional_empty_has_no_part(self):
        plan, _ = probe.make_group_candidate(
            GROUP_PAGE, ORIGIN, 5, required=False, selected=()
        )
        self.assertNotIn(
            "services[]", probe.grouped(probe.decode_parts(*probe.wire(plan)))
        )

    def test_incomplete_unknown_and_mismatched_fixtures_are_rejected(self):
        for args in (
            (4, True, ()),
            (4, True, ("UNKNOWN",)),
            (4, True, ("OEM", "OEM")),
            (4, False, ()),
            (5, True, ("OEM",)),
            (0, True, ("OEM",)),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                probe.make_group_candidate(
                    GROUP_PAGE, ORIGIN, args[0], required=args[1], selected=args[2]
                )
        for changed in (
            GROUP_PAGE.replace('value="OEM"', 'value="OTHER"'),
            GROUP_PAGE.replace(
                'type="checkbox" name="services[]"', 'type="radio" name="services[]"'
            ),
            GROUP_PAGE.replace('name="services[]"', 'name="other[]"'),
            GROUP_PAGE.replace('value="OEM"', 'disabled value="OEM"'),
        ):
            with self.subTest(changed=changed[:20]), self.assertRaises(ValueError):
                probe.make_group_candidate(
                    changed, ORIGIN, 4, required=True, selected=("OEM",)
                )

    def test_revision_rejected_without_http(self):
        plan, _ = probe.make_group_candidate(
            GROUP_PAGE, ORIGIN, 4, required=True, selected=("OEM",)
        )
        current, _ = probe.make_group_candidate(
            GROUP_PAGE, ORIGIN, 4, required=True, selected=("Website",)
        )
        with self.assertRaises(ValueError):
            probe.verified_wire(probe.snapshot(plan), current)

    def test_opt_in_and_remote_origin_rejected(self):
        with (
            patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "0"}),
            self.assertRaises(ValueError),
        ):
            probe.make_group_candidate(
                GROUP_PAGE, ORIGIN, 4, required=True, selected=("OEM",)
            )
        with self.assertRaises(ValueError):
            probe.make_group_candidate(
                GROUP_PAGE, "https://real.example", 4, required=True, selected=("OEM",)
            )


if __name__ == "__main__":
    unittest.main()
