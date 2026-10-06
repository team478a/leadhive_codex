"""Offline synthetic evidence. Network, DB and application entrypoints forbidden."""

import json
import socket
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import storage_contract as s
from pydantic import ValidationError
from test_observer import HTML


class StorageTests(unittest.TestCase):
    def setUp(self):
        project = uuid4()
        self.binding = s.Binding(
            project_id=project,
            company_project_id=project,
            job_project_id=project,
            company_id=uuid4(),
            operation_job_id=uuid4(),
            run_id=uuid4(),
            lease_worker_id=uuid4(),
            initiated_by_user_id=uuid4(),
            attempt_number=1,
            company_source_hash="a" * 64,
        )
        self.now = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
        self.evidence_id = uuid4()
        self.dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
        )
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.connect = patch.object(
            socket.socket, "connect", side_effect=AssertionError("HTTP forbidden")
        )
        self.connect.start()
        self.addCleanup(self.connect.stop)

    def build(self, **overrides):
        kwargs = {
            "evidence_id": self.evidence_id,
            "body": HTML.encode(),
            "robots": b"User-agent: *\nAllow: /\n",
            "pinned_ips": ("8.8.8.8", "8.8.8.8"),
            "media_type": "text/html",
            "started_at": self.now - timedelta(seconds=1),
            "observed_at": self.now,
            "now": self.now,
        }
        kwargs.update(overrides)
        return s.build(self.binding, **kwargs)

    def rewritten(self, value, mutate, *, rehash=False):
        data = json.loads(s.encode(value))
        mutate(data)
        if rehash:
            # Even a caller who recomputes a hash cannot bypass binding/schema.
            data["snapshot_hash"] = s.digest(
                json.dumps(
                    data["snapshot"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
        return json.dumps(data).encode()

    def test_round_trip_is_deterministic_non_authoritative_and_redacted(self):
        value = self.build()
        self.assertEqual(value, self.build())
        self.assertEqual(s.decode(s.encode(value), self.binding, now=self.now), value)
        snap = value.snapshot
        self.assertFalse(snap.execution_allowed)
        self.assertFalse(snap.eligible_for_approval)
        self.assertEqual(
            (snap.sales_permission, snap.captcha_state), ("UNCERTAIN", "UNVERIFIED")
        )
        self.assertEqual(snap.source_kind, "STATIC_HTML_UNVERIFIED")
        text = s.encode(value).decode()
        for excluded in [
            "_wpcf7",
            "checkbox_value",
            "feedback",
            "rest_root",
            "declared_action",
            "<form",
            "hidden",
        ]:
            self.assertNotIn(excluded, text)
        self.assertNotEqual(value.snapshot_hash, snap.parser_evidence_hash)

    def test_label_and_name_sensitive_text_removed_and_values_never_projected(self):
        html = HTML.replace("your-name", "api_key").replace(
            "Name<input", "secret@example.com<input"
        )
        html = html.replace('value="subscribe"', 'value="smtp-secret-value"')
        value = self.build(body=html.encode())
        text = s.encode(value).decode()
        for secret in ["api_key", "secret@example.com", "smtp-secret-value"]:
            self.assertNotIn(secret, text)
        control = value.snapshot.structure_summary.controls[0]
        self.assertEqual(control.name, "[REDACTED]")
        self.assertTrue(control.redacted)

    def test_long_labels_truncated_and_default_checked_is_only_observation(self):
        value = self.build(
            body=HTML.replace("Name<input", "長" * 251 + "<input").encode()
        )
        control = value.snapshot.structure_summary.controls[0]
        self.assertEqual(len(control.label), 250)
        self.assertTrue(control.truncated)
        self.assertTrue(value.snapshot.structure_summary.controls[-1].default_checked)
        self.assertNotIn("selections", s.encode(value).decode())

    def test_blocked_captcha_and_unsupported_have_no_execution_structure(self):
        for body, decision in [
            (HTML + "<p>営業目的のお問い合わせはお断り</p>", "BLOCKED"),
            (
                HTML + "<script src='https://captcha.example/widget.js'></script>",
                "HUMAN_REQUIRED",
            ),
            ("<html>no form</html>", "UNSUPPORTED"),
        ]:
            with self.subTest(decision=decision):
                value = self.build(body=body.encode())
                self.assertEqual(value.snapshot.decision, decision)
                self.assertIsNone(value.snapshot.structure_summary)
                self.assertFalse(value.snapshot.execution_allowed)
                s.decode(s.encode(value), self.binding, now=self.now)

    def test_authority_unknown_version_extra_fields_and_wrong_reason_rejected_even_rehashed(
        self,
    ):
        for field, replacement in [
            ("eligible_for_approval", True),
            ("execution_allowed", True),
            ("source_kind", "CONTROLLED_FIXTURE"),
            ("provenance", "REAL_SITE"),
            ("snapshot_schema_version", "unknown"),
            ("observer_version", "unknown"),
            ("fetch_policy_version", "unknown"),
            ("redaction_version", "unknown"),
            ("sales_permission", "ALLOWED"),
            ("captcha_state", "CAPTCHA_NONE"),
            ("reason_code", "SALES_PROHIBITED"),
            ("credential", "secret"),
        ]:
            with self.subTest(field=field), self.assertRaises(s.ContractBlocked):
                data = self.rewritten(
                    self.build(),
                    lambda d, field=field, replacement=replacement: d[
                        "snapshot"
                    ].update({field: replacement}),
                    rehash=True,
                )
                s.decode(data, self.binding, now=self.now)

    def test_hash_tampering_and_nested_frozen_models(self):
        value = self.build()
        data = self.rewritten(
            value, lambda d: d["snapshot"].update({"body_sha256": "b" * 64})
        )
        with self.assertRaises(s.ContractBlocked):
            s.decode(data, self.binding, now=self.now)
        bypass = value.model_copy(update={"snapshot_hash": "b" * 64})
        with self.assertRaises(s.ContractBlocked):
            s.encode(bypass)
        with self.assertRaises(s.ContractBlocked):
            s.check_current(bypass, self.binding, now=self.now)
        for obj, field, replacement in [
            (value, "snapshot_hash", "b" * 64),
            (value.snapshot, "execution_allowed", True),
            (value.snapshot.binding, "project_id", uuid4()),
            (value.snapshot.structure_summary.controls[0], "name", "changed"),
        ]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                setattr(obj, field, replacement)

    def test_project_job_source_actor_run_attempt_and_lease_are_current_boundaries(
        self,
    ):
        value = self.build()
        for field in [
            "company_id",
            "operation_job_id",
            "run_id",
            "lease_worker_id",
            "initiated_by_user_id",
        ]:
            expected = s.Binding.model_validate(
                self.binding.model_dump() | {field: uuid4()}
            )
            with self.subTest(field=field), self.assertRaises(s.ContractBlocked):
                s.decode(s.encode(value), expected, now=self.now)
        for field, replacement in [
            ("company_source_hash", "b" * 64),
            ("attempt_number", 2),
        ]:
            expected = s.Binding.model_validate(
                self.binding.model_dump() | {field: replacement}
            )
            with self.subTest(field=field), self.assertRaises(s.ContractBlocked):
                s.decode(s.encode(value), expected, now=self.now)
        project = uuid4()
        other = s.Binding.model_validate(
            self.binding.model_dump()
            | {
                "project_id": project,
                "company_project_id": project,
                "job_project_id": project,
            }
        )
        with self.assertRaises(s.ContractBlocked):
            s.decode(s.encode(value), other, now=self.now)
        for field in ["company_project_id", "job_project_id"]:
            with self.assertRaises(ValidationError):
                s.Binding.model_validate(self.binding.model_dump() | {field: uuid4()})

    def test_rehashing_another_project_does_not_pass_expected_binding(self):
        project = str(uuid4())
        data = self.rewritten(
            self.build(),
            lambda d: d["snapshot"]["binding"].update(
                {
                    "project_id": project,
                    "company_project_id": project,
                    "job_project_id": project,
                }
            ),
            rehash=True,
        )
        with self.assertRaises(s.ContractBlocked):
            s.decode(data, self.binding, now=self.now)

    def test_expiration_retirement_future_and_invalid_timestamps(self):
        value = self.build()
        for now, retired in [
            (self.now + timedelta(hours=24), False),
            (self.now - timedelta(seconds=1), False),
            (self.now, True),
        ]:
            with self.assertRaises(s.ContractBlocked):
                s.decode(s.encode(value), self.binding, now=now, retired=retired)
        for kwargs in [
            {"ttl": timedelta(hours=25)},
            {"ttl": timedelta(0)},
            {"started_at": self.now + timedelta(seconds=1)},
            {"started_at": self.now - timedelta(seconds=31)},
            {"observed_at": self.now + timedelta(seconds=1)},
            {"now": self.now.replace(tzinfo=None)},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(s.ContractBlocked):
                self.build(**kwargs)

    def test_acquisition_size_type_and_private_ip_rejected(self):
        for kwargs in [
            {"body": b""},
            {"body": b"x" * 65537},
            {"robots": b""},
            {"robots": b"x" * 16385},
            {"media_type": "application/json"},
            {"pinned_ips": ("8.8.8.8", "127.0.0.1")},
        ]:
            with (
                self.subTest(kwargs=list(kwargs)),
                self.assertRaises(s.ContractBlocked),
            ):
                self.build(**kwargs)

    def test_json_size_depth_elements_duplicate_key_and_malformed_rejected(self):
        value = self.build()
        for data in [
            b"x" * (s.LIMIT + 1),
            b"[" * 9 + b"0" + b"]" * 9,
            b"[" + b"0," * 2050 + b"0]",
            b"\xff",
            b"{",
            b'{"snapshot":{},"snapshot":{}}',
        ]:
            with self.subTest(size=len(data)), self.assertRaises(s.ContractBlocked):
                s.decode(data, self.binding, now=self.now)
        data = self.rewritten(
            value,
            lambda d: d["snapshot"]["structure_summary"]["controls"][0].update(
                {"label": "secret@example.com"}
            ),
            rehash=True,
        )
        with self.assertRaises(s.ContractBlocked) as caught:
            s.decode(data, self.binding, now=self.now)
        self.assertNotIn("secret@example.com", str(caught.exception))

    def test_fifty_controls_fit_but_large_utf8_projection_is_rejected(self):
        for label, accepted in [("Additional", True), ("長" * 250, False)]:
            additional = "".join(
                f'<label>{label}<input name="extra-{i}" type="text"></label>'
                for i in range(45)
            )
            body = HTML.replace("</form>", additional + "</form>").encode()
            self.assertLessEqual(len(body), 65536)
            if accepted:
                value = self.build(body=body)
                self.assertEqual(len(value.snapshot.structure_summary.controls), 50)
                s.decode(s.encode(value), self.binding, now=self.now)
            else:
                with self.assertRaises(s.ContractBlocked):
                    self.build(body=body)

    def test_hash_binds_observed_content_robots_and_acquisition_metadata(self):
        original = self.build()
        for kwargs in [
            {"body": HTML.replace("Name<input", "Contact name<input").encode()},
            {"robots": b"User-agent: *\nDisallow:\n"},
            {"pinned_ips": ("8.8.8.8", "1.1.1.1")},
            {"media_type": "text/html; charset=utf-8"},
        ]:
            with self.subTest(kwargs=list(kwargs)):
                self.assertNotEqual(
                    self.build(**kwargs).snapshot_hash, original.snapshot_hash
                )


if __name__ == "__main__":
    unittest.main()
