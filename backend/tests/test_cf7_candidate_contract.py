"""Pure candidate tests. PYTHONPATH=backend; no app startup, DB, DNS or HTTP."""

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from pydantic import ValidationError

from app.services.cf7_candidate_contract import (
    CF7Candidate,
    Control,
    Selection,
    digest,
    snapshot,
    validate_snapshot,
    wire,
)
from app.services.form_adapter_contract import ExecutableFormPlan
from app.services.form_execution_plan import InputValue, PlanError


def candidate() -> CF7Candidate:
    h = {
        "_wpcf7": "7",
        "_wpcf7_version": "6.1.4",
        "_wpcf7_locale": "en_US",
        "_wpcf7_unit_tag": "wpcf7-f7-p12-o1",
        "_wpcf7_container_post": "12",
        "_wpcf7_posted_data_hash": "",
    }
    fields = {
        "your-name": "Lab operator",
        "your-email": "operator@example.com",
        "your-message": "  日本語\n第二行  ",
        "consent": "1",
    }
    return CF7Candidate(
        project_id=UUID(int=1),
        company_id=UUID(int=2),
        source_draft_id=UUID(int=3),
        form_profile_id=UUID(int=4),
        payload_version=1,
        form_url="https://managed.example/contact/",
        rest_root="https://managed.example/wp-json/",
        endpoint="https://managed.example/wp-json/contact-form-7/v1/contact-forms/7/feedback",
        form_id=7,
        captcha_state="NONE",
        dom_fingerprint="a" * 64,
        hidden=tuple(InputValue(name=k, value=v) for k, v in h.items()),
        controls=tuple(
            Control(
                name=k,
                kind=kind,
                required=True,
                label=label,
                checkbox_value="1" if kind == "checkbox" else "",
            )
            for k, kind, label in [
                ("your-name", "text", "Name"),
                ("your-email", "email", "Email"),
                ("your-message", "textarea", "Message"),
                ("consent", "checkbox", "Consent to this inquiry"),
            ]
        ),
        selections=(Selection(name="consent", checked=True),),
        sender=tuple(
            InputValue(name=k, value=v)
            for k, v in {
                "name": "Lab operator",
                "email": "operator@example.com",
                "company": "",
                "phone": "",
            }.items()
        ),
        subject="",
        body=fields["your-message"],
        name_field="your-name",
        email_field="your-email",
        body_field="your-message",
        field_values=tuple(InputValue(name=k, value=v) for k, v in fields.items()),
    )


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.plan = candidate()
        self.saved = snapshot(self.plan)
        self.bound = {
            "expected_hash": digest(self.saved),
            "expected_version": 1,
            "project_id": self.plan.project_id,
            "company_id": self.plan.company_id,
            "source_draft_id": self.plan.source_draft_id,
            "form_profile_id": self.plan.form_profile_id,
        }

    def test_snapshot_exact_binding_json_round_trip(self):
        restored = CF7Candidate.model_validate_json(json.dumps(self.saved["contract"]))
        validate_snapshot(self.saved, restored, **self.bound)
        self.assertEqual(snapshot(restored), self.saved)

    def test_wire_hash_exact_crlf_utf8_no_trim(self):
        content_type, body = wire(self.plan)
        self.assertIn("boundary=----LeadHiveCF7", content_type)
        self.assertIn("  日本語\r\n第二行  ".encode(), body)
        self.assertEqual(hashlib.sha256(body).hexdigest(), self.saved["wire_sha256"])
        self.assertEqual(len(body), self.saved["wire_size"])
        self.assertTrue(body.endswith(b"--\r\n"))
        self.assertEqual(body.count(b"Content-Disposition:"), 10)
        self.assertEqual(wire(self.plan), (content_type, body))

    def test_source_newlines_are_bound_even_if_wire_semantics_match(self):
        data = self.plan.model_dump(mode="python")
        data["body"] = data["body"].replace("\n", "\r\n")
        data["field_values"] = tuple(
            InputValue(name=v.name, value=v.value.replace("\n", "\r\n"))
            for v in self.plan.field_values
        )
        current = CF7Candidate.model_validate(data)
        self.assertNotEqual(snapshot(current), self.saved)
        with self.assertRaises(PlanError):
            validate_snapshot(self.saved, current, **self.bound)

    def test_every_metadata_revision_invalidates_snapshot(self):
        changes = {
            "project_id": UUID(int=11),
            "company_id": UUID(int=12),
            "source_draft_id": UUID(int=13),
            "form_profile_id": UUID(int=14),
            "payload_version": 2,
            "form_url": "https://managed.example/contact/changed",
            "dom_fingerprint": "b" * 64,
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                data = self.plan.model_dump(mode="python")
                data[key] = value
                current = CF7Candidate.model_validate(data)
                with self.assertRaises(PlanError):
                    validate_snapshot(self.saved, current, **self.bound)

    def test_valid_route_or_host_change_requires_new_snapshot(self):
        for root in (
            "https://managed.example/?rest_route=/",
            "https://managed.example/index.php?rest_route=/",
            "https://other.example/wp-json/",
        ):
            data = self.plan.model_dump(mode="python")
            data["form_url"] = root.split("/", 3)[0] + "//" + root.split("/")[2] + "/contact/"
            data["rest_root"] = root
            data["endpoint"] = root + "contact-form-7/v1/contact-forms/7/feedback"
            current = CF7Candidate.model_validate(data)
            with self.assertRaises(PlanError):
                validate_snapshot(self.saved, current, **self.bound)

    def test_unsafe_or_unknown_destination_and_versions(self):
        changes = [
            ("form_url", "http://managed.example/contact/"),
            ("form_url", "https://u:p@managed.example/contact"),
            ("form_url", "https://127.0.0.1/contact"),
            ("form_url", "https://managed.example:443/contact"),
            ("endpoint", self.plan.endpoint + "?override=1"),
            ("endpoint", "https://other.example/feedback"),
            ("rest_root", "https://managed.example/custom/"),
            ("plugin_version", "6.2"),
            ("captcha_state", "UNKNOWN"),
            ("captcha_state", "RECAPTCHA"),
            ("execution_path", "JS_CONFIRMATION"),
            ("method", "GET"),
            ("encoding_version", "raw-lf"),
            ("environment", "PRODUCTION"),
            ("delivery_method", "form_adapter"),
            ("payload_version", True),
            ("unknown", "value"),
        ]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                data = self.plan.model_dump(mode="python")
                data[key] = value
                with self.assertRaises(ValidationError):
                    CF7Candidate.model_validate(data)

    def test_hidden_changes_and_tokens_fail_closed(self):
        for key, value in [
            ("_wpcf7", "8"),
            ("_wpcf7_unit_tag", "wpcf7-f8-p12-o1"),
            ("_wpcf7_version", "6.2"),
            ("_wpcf7_posted_data_hash", "used"),
            ("_wpcf7_container_post", "13"),
            ("_wpcf7_locale", "x\r\nX:bad"),
        ]:
            data = self.plan.model_dump(mode="python")
            data["hidden"] = tuple(
                InputValue(name=v.name, value=value if v.name == key else v.value)
                for v in self.plan.hidden
            )
            with self.subTest(key=key), self.assertRaises(ValidationError):
                CF7Candidate.model_validate(data)
        data["hidden"] = (
            *self.plan.hidden[:-1],
            InputValue(name="nonce", value="unknown"),
        )
        with self.assertRaises(ValidationError):
            CF7Candidate.model_validate(data)

    def test_message_and_sender_must_match_mapped_fields(self):
        for key, value in [
            ("body", "changed"),
            ("name_field", "your-email"),
            ("subject", "unmapped subject"),
        ]:
            data = self.plan.model_dump(mode="python")
            data[key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                CF7Candidate.model_validate(data)
        current = self.plan.model_copy(update={"body": "changed"})
        with self.assertRaises(ValidationError):
            snapshot(current)

    def test_coordinated_message_and_sender_revisions_still_require_new_approval(self):
        for name, replacement in [
            ("your-message", "Changed 日本語 message"),
            ("your-name", "Different operator"),
        ]:
            data = self.plan.model_dump(mode="python")
            data["field_values"] = tuple(
                InputValue(name=v.name, value=replacement if v.name == name else v.value)
                for v in self.plan.field_values
            )
            if name == "your-message":
                data["body"] = replacement
            else:
                data["sender"] = tuple(
                    InputValue(name=v.name, value=replacement if v.name == "name" else v.value)
                    for v in self.plan.sender
                )
            current = CF7Candidate.model_validate(data)
            with self.subTest(name=name), self.assertRaises(PlanError):
                validate_snapshot(self.saved, current, **self.bound)

    def test_checkbox_label_and_explicit_choices_bound(self):
        data = self.plan.model_dump(mode="python")
        data["controls"] = tuple(
            c.model_copy(update={"label": "Changed consent text"}) if c.name == "consent" else c
            for c in self.plan.controls
        )
        current = CF7Candidate.model_validate(data)
        with self.assertRaises(PlanError):
            validate_snapshot(self.saved, current, **self.bound)
        for selection in [(), (Selection(name="consent", checked=False),)]:
            data["selections"] = selection
            with self.assertRaises(ValidationError):
                CF7Candidate.model_validate(data)

    def test_duplicate_unknown_controls_and_fields(self):
        for key, values in [
            ("controls", (*self.plan.controls, self.plan.controls[0])),
            ("field_values", (*self.plan.field_values, self.plan.field_values[0])),
            (
                "field_values",
                (*self.plan.field_values, InputValue(name="unknown", value="x")),
            ),
        ]:
            data = self.plan.model_dump(mode="python")
            data[key] = values
            with self.subTest(key=key), self.assertRaises(ValidationError):
                CF7Candidate.model_validate(data)

    def test_control_order_and_type_changes_are_bound(self):
        data = self.plan.model_dump(mode="python")
        data["controls"] = tuple(reversed(self.plan.controls))
        with self.assertRaises(PlanError):
            validate_snapshot(self.saved, CF7Candidate.model_validate(data), **self.bound)
        with self.assertRaises(ValidationError):
            Control(name="upload", kind="file", required=False, label="", checkbox_value="")

    def test_saved_wire_hash_and_outer_hash_not_replaceable(self):
        for key, value in [
            ("wire_sha256", "c" * 64),
            ("wire_size", 1),
            ("content_type", "application/json"),
            ("contract_hash", "d" * 64),
        ]:
            changed = copy.deepcopy(self.saved)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(PlanError):
                validate_snapshot(
                    changed,
                    self.plan,
                    **{**self.bound, "expected_hash": digest(changed)},
                )

    def test_server_id_hash_version_conflicts(self):
        for key, value in [
            ("expected_hash", "e" * 64),
            ("expected_version", 2),
            ("expected_version", True),
            ("company_id", UUID(int=99)),
            ("form_profile_id", UUID(int=98)),
        ]:
            with self.subTest(key=key), self.assertRaises(PlanError):
                validate_snapshot(self.saved, self.plan, **{**self.bound, key: value})

    def test_not_convertible_to_existing_executable_adapter(self):
        with self.assertRaises(ValidationError):
            ExecutableFormPlan.model_validate(self.plan.model_dump(mode="python"))
        with self.assertRaises(ValidationError):
            self.plan.body = "mutated"

    def test_observed_dom_change_invalidates_fingerprint_without_http(self):
        # Reuse the managed lab observer; do not widen its loopback boundary.
        path = Path(__file__).parents[2] / "scripts" / "cf7_lab" / "protocol.py"
        spec = importlib.util.spec_from_file_location("leadhive_contract_lab_observer", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        html = (
            '<script>var wpcf7 = {"api":{"root":"http://127.0.0.1:19876/wp-json/",'
            '"namespace":"contact-form-7/v1"}};</script>'
            '<form class="wpcf7-form" method="post" action="/contact/">'
        )
        for item in self.plan.hidden:
            html += f'<input type="hidden" name="{item.name}" value="{item.value}">'
        html += (
            '<input name="your-name"><input type="email" name="your-email">'
            '<textarea name="your-message"></textarea>'
            '<label>Consent to this inquiry<input type="checkbox" name="consent" value="1">'
            "</label></form>"
        )
        base = module.observe(html, "http://127.0.0.1:19876")
        saved_plan = self.plan.model_copy(update={"dom_fingerprint": base.fingerprint})
        saved = snapshot(saved_plan)
        for changed in [
            html.replace("Consent to this inquiry", "Changed consent"),
            html.replace('name="your-name"', 'name="other-name"'),
            html.replace('/contact/"', '/changed/"'),
        ]:
            observed = module.observe(changed, "http://127.0.0.1:19876")
            current = saved_plan.model_copy(update={"dom_fingerprint": observed.fingerprint})
            with self.assertRaises(PlanError):
                validate_snapshot(saved, current, **{**self.bound, "expected_hash": digest(saved)})

    def test_non_executable_contract_performs_no_dns(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("Unexpected DNS")):
            validate_snapshot(self.saved, self.plan, **self.bound)

    def test_control_text_transformations_fail_closed(self):
        for text in ("Lab\noperator", "Lab\r\noperator", "Lab\x00operator"):
            data = self.plan.model_dump(mode="python")
            data["sender"] = tuple(
                InputValue(name=v.name, value=text if v.name == "name" else v.value)
                for v in self.plan.sender
            )
            data["field_values"] = tuple(
                InputValue(name=v.name, value=text if v.name == "your-name" else v.value)
                for v in self.plan.field_values
            )
            with self.subTest(text=text), self.assertRaises(ValidationError):
                CF7Candidate.model_validate(data)


if __name__ == "__main__":
    unittest.main()
