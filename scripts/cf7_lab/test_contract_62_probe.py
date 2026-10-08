import os
import unittest
from unittest.mock import patch

from app.services.cf7_62_contract import snapshot, validate_snapshot, wire
from app.services.cf7_candidate_contract import CF7Candidate, digest
from contract_62_probe import make_candidate_62
from group_probe import decode_parts
from test_contract_probe import ORIGIN
from test_version_probe import PAGE62
from version_probe import fixture_wire


class Contract62Tests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"CF7_PROTOCOL_LAB": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_dom_order_and_full_fingerprint(self):
        plan, observed = make_candidate_62(PAGE62, ORIGIN)
        self.assertEqual(
            decode_parts(*wire(plan)), fixture_wire(PAGE62, ORIGIN, mixed=True)[1]
        )
        self.assertEqual(plan.base.dom_fingerprint, observed.fingerprint)
        self.assertFalse(plan.execution_allowed)
        self.assertFalse(plan.eligible_for_approval)
        with self.assertRaises(ValueError):
            CF7Candidate.model_validate(plan.base.model_dump())

    def test_scope_snapshot_and_changes(self):
        plan, _ = make_candidate_62(PAGE62, ORIGIN)
        saved = snapshot(plan)
        args = {
            "expected_hash": digest(saved),
            "expected_version": 1,
            "project_id": plan.base.project_id,
            "company_id": plan.base.company_id,
            "source_draft_id": plan.base.source_draft_id,
            "form_profile_id": plan.base.form_profile_id,
        }
        validate_snapshot(saved, plan, **args)
        for changed in (
            plan.model_copy(update={"order": tuple(reversed(plan.order))}),
            plan.model_copy(update={"execution_allowed": True}),
            plan.model_copy(update={"order": plan.order[:-1]}),
            plan.model_copy(
                update={
                    "base": plan.base.model_copy(update={"plugin_version": "6.1.4"})
                }
            ),
            plan.model_copy(
                update={
                    "base": plan.base.model_copy(update={"dom_fingerprint": "0" * 64})
                }
            ),
        ):
            with self.assertRaises(ValueError):
                validate_snapshot(saved, changed, **args)
        for field, value in (
            ("expected_version", 2),
            ("project_id", plan.base.company_id),
            ("expected_hash", "0" * 64),
        ):
            with self.assertRaises(ValueError):
                validate_snapshot(saved, plan, **(args | {field: value}))

    def test_dom_and_version_rejected(self):
        for page in (
            PAGE62.replace('value="6.2"', 'value="6.1.4"'),
            PAGE62.replace('value="OEM"', 'value="UNKNOWN"'),
            PAGE62.replace("fixture-business-context", "SECRET"),
            PAGE62.replace("wpcf7-acceptance", "wpcf7-acceptance optional"),
        ):
            with self.assertRaises(ValueError):
                make_candidate_62(page, ORIGIN)

    def test_standard_contract(self):
        plan, _ = make_candidate_62(PAGE62, ORIGIN, mixed=False)
        self.assertEqual(len(plan.order), 10)
        self.assertEqual(decode_parts(*wire(plan)), fixture_wire(PAGE62, ORIGIN)[1])
