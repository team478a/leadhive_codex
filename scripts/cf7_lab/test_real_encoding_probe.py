import os
import unittest
from unittest.mock import patch

import contract_probe  # noqa: F401 -- establish pure backend import path.
from app.services.cf7_real_contract_preview import preview
from app.services.cf7_real_encoding import encode
from real_encoding_probe import make_inputs
from test_contract_probe import HTML, ORIGIN


class RealEncodingProbeTests(unittest.TestCase):
    def page(self, version):
        html = (
            '<link rel="https://api.w.org/" href="'
            + ORIGIN
            + '/wp-json/">'
            + HTML.replace("6.1.4", version)
        )
        start = html.index('<span class="wpcf7-acceptance"')
        end = html.index("</span>", start) + len("</span>")
        html = html[:start] + html[end:]
        return html.replace(
            'name="your-name"', 'maxlength="400" name="your-name"'
        ).replace('name="your-message"', 'maxlength="2000" name="your-message"')

    def test_pinned_versions_keep_real_constraints_and_no_send_authority(self):
        with patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"}):
            for version in ("6.1.4", "6.2"):
                observed, report, observation = make_inputs(
                    self.page(version), ORIGIN, ORIGIN + "/contact/", version
                )
                current = preview(report, observation)
                self.assertEqual(current["status"], "PREVIEW_ONLY")
                self.assertFalse(current["execution_allowed"])
                self.assertEqual(
                    observation["cf7_static"]["contract_evidence"]["controls"][0][
                        "maxlength"
                    ],
                    400,
                )
                self.assertGreater(
                    len(
                        encode(
                            report,
                            observation,
                            expected_contract_hash=current["contract_hash"],
                        ).body
                    ),
                    0,
                )
                self.assertTrue(observed.endpoint.startswith(ORIGIN))

    def test_constraints_and_unsupported_versions_are_not_removed_to_pass(self):
        with patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"}):
            for html, version in (
                (
                    self.page("6.2").replace('maxlength="400"', 'maxlength="PRIVATE"'),
                    "6.2",
                ),
                (self.page("6.2"), "6.2.1"),
            ):
                with self.assertRaises(ValueError):
                    make_inputs(html, ORIGIN, ORIGIN + "/contact/", version)

    def test_theme_search_form_does_not_replace_the_cf7_form(self):
        with patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"}):
            html = '<form method="get"><input name="search"></form>' + self.page("6.2")
            _, report, observation = make_inputs(
                html, ORIGIN, ORIGIN + "/contact/", "6.2"
            )
            self.assertEqual(preview(report, observation)["status"], "PREVIEW_ONLY")

    def test_wp_json_slash_escaping_is_preserved_in_fixed_origin_mapping(self):
        with patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"}):
            html = self.page("6.2").replace(
                '"root":"' + ORIGIN + '/wp-json/"',
                '"root":"' + (ORIGIN + "/wp-json/").replace("/", r"\/") + '"',
            )
            _, report, observation = make_inputs(
                html, ORIGIN, ORIGIN + "/contact/", "6.2"
            )
            self.assertEqual(preview(report, observation)["status"], "PREVIEW_ONLY")


if __name__ == "__main__":
    unittest.main()
