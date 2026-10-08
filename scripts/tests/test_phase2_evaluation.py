"""Offline preparation checks; synthetic receipts are not Human Truth."""

import importlib.util
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "phase2", Path(__file__).resolve().parents[1] / "prepare_phase2_evaluation.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def observation(outcome=None, reason="test evidence"):
    return {
        "snapshot_id": "test-observation",
        "snapshot_hash": "a" * 64,
        "payload": {
            "website": "https://example.test/",
            "company_name": "<script>alert(1)</script>",
        },
        "query_region": "test-region",
        "human_review": None
        if outcome is None
        else {
            "reviewer": "synthetic-human",
            "reviewed_at": "2026-10-09T00:00:00Z",
            "version": 1,
            "snapshot_hash": "a" * 64,
            "outcome": outcome,
            "reason": reason,
            "evidence_url": "https://example.test/evidence",
            "duration_seconds": 12,
        },
    }


class PreparationTests(unittest.TestCase):
    def test_no_review_null(self):
        result = module.collection_report([observation()])
        self.assertIsNone(result["raw_strict_precision"])
        self.assertEqual(result["unreviewed"], 1)
        self.assertIsNone(result["dimension_metrics"]["official_site"]["strict"])

    def test_empty_denominator(self):
        self.assertIsNone(module.collection_report([])["review_coverage"])

    def test_uncertain_and_duplicate(self):
        result = module.collection_report(
            [observation("CORRECT"), observation("UNCERTAIN"), observation("DUPLICATE")]
        )
        self.assertAlmostEqual(result["raw_strict_precision"], 1 / 3)
        self.assertEqual(result["raw_resolved_precision"], 0.5)
        self.assertAlmostEqual(result["duplicate_rate"], 1 / 3)

    def test_all_uncertain(self):
        self.assertIsNone(
            module.collection_report([observation("UNCERTAIN")])[
                "raw_resolved_precision"
            ]
        )

    def test_draft_ignored(self):
        row = observation()
        row["worksheet"] = {"outcome": "CORRECT", "status": "APPROVED"}
        self.assertEqual(module.collection_report([row])["formal_raw_reviewed"], 0)

    def test_stale_hash_rejected(self):
        row = observation("CORRECT")
        row["human_review"]["snapshot_hash"] = "b" * 64
        with self.assertRaises(ValueError):
            module.collection_report([row])

    def test_missing_reviewer_rejected(self):
        row = observation("CORRECT")
        row["human_review"]["reviewer"] = ""
        with self.assertRaises(ValueError):
            module.collection_report([row])

    def test_form_reasons_overlap_not_causal(self):
        result = module.form_report(
            {
                "companies": [
                    {
                        "assessment": {
                            "status": "HOLD",
                            "reasons": [{"code": "A"}, {"code": "A"}, {"code": "B"}],
                        },
                        "forms": [],
                    }
                ]
            }
        )
        self.assertEqual(result["reasons"][0]["affected"], 1)
        self.assertEqual(result["reasons"][0]["sole_reason"], 0)
        self.assertIsNone(result["reasons"][0]["potential_unlock"])

    def test_safe_url(self):
        for url in (
            "javascript:alert(1)",
            "https://user:secret@example.test",
            "https://example.test/?key=secret",
        ):
            self.assertEqual(module.safe_url(url), "")

    def test_html_escape_no_automatic_access(self):
        view = module.render_review([observation()])
        self.assertNotIn("<script>", view)
        self.assertIn("&lt;script&gt;", view)
        self.assertIn("form-action", view)
        self.assertNotIn("<img", view)

    def test_model_final_decisions_differ(self):
        result = {
            "score": 90,
            "rank": "対象外",
            "is_target": False,
            "business_type": "test",
            "summary": "unknown",
            "reason": "unknown",
            "strengths": [],
            "concerns": ["unknown"],
            "recommended_approach": "unknown",
        }
        with patch.object(
            socket.socket, "connect", side_effect=AssertionError("No network")
        ):
            preview = module.decision_preview(result, {})
        self.assertFalse(preview["raw_model"]["is_target"])
        self.assertTrue(preview["final"]["is_target"])

    def test_schema_invalid(self):
        with self.assertRaises(ValueError):
            module.decision_preview({"score": 101}, {})

    def test_dimensions_separate_unknown_not_applicable(self):
        reason = json.dumps(
            {
                "definition": "phase2-truth-v1",
                "target_fit": "CORRECT",
                "official_site": "UNKNOWN",
                "contact_accuracy": "NOT_APPLICABLE",
            }
        )
        result = module.collection_report([observation("UNCERTAIN", reason)])
        self.assertEqual(result["dimension_metrics"]["target_fit"]["strict"], 1)
        self.assertIsNone(result["dimension_metrics"]["official_site"]["strict"])
        self.assertIsNone(result["dimension_metrics"]["official_site"]["resolved"])
        self.assertIsNone(result["dimension_metrics"]["contact_accuracy"]["strict"])

    def test_context_missing_conditions_stops_paid_execution(self):
        row = observation()
        inputs = module.freeze_inputs([row])
        self.assertFalse(inputs[0]["ready_for_paid_evaluation"])
        self.assertIn("frozen TargetProfile", inputs[0]["missing"])


if __name__ == "__main__":
    unittest.main()
