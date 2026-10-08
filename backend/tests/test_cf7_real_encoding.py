from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default

import pytest

from app.services.cf7_candidate_contract import digest
from app.services.cf7_real_contract_preview import preview
from app.services.cf7_real_encoding import encode, summarize, validate_saved
from app.services.form_execution_plan import PlanError
from tests.test_cf7_real_contract_preview import fixture


def mime_parts(content_type, body):
    message = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
    )
    return [
        (
            part.get_param("name", header="content-disposition"),
            part.get_payload(decode=True).decode("utf-8"),
        )
        for part in message.iter_parts()
    ]


@pytest.mark.parametrize("version", ["6.1.4", "6.2"])
def test_encoding_keeps_order_unicode_newlines_and_has_no_authority(version):
    report, observation = fixture(version)
    report["snapshot"]["rows"][0]["values"] = ["日本語\n改行\r単独\r\n末尾😀"]
    report["snapshot_hash"] = digest(report["snapshot"])
    current = preview(report, observation)
    encoded = encode(report, observation, expected_contract_hash=current["contract_hash"])
    parts = mime_parts(encoded.content_type, encoded.body)
    assert [n for n, _ in parts] == [p["name"] for p in current["contract"]["parts"]]
    assert dict(parts)["body"] == "日本語\r\n改行\r\n単独\r\n末尾😀"
    summary = summarize(encoded)
    assert summary["wire_size"] == len(encoded.body)
    assert not summary["execution_allowed"] and not summary["eligible_for_approval"]
    assert "日本語" not in str(summary) and "sender@example.com" not in str(summary)
    validate_saved(summary, report, observation, expected_contract_hash=current["contract_hash"])


@pytest.mark.parametrize(
    "change", ["target", "draft", "scope", "order", "version", "expired", "approval", "wire"]
)
def test_saved_encoding_rejects_changes(change):
    report, observation = fixture()
    current = preview(report, observation)
    expected = current["contract_hash"]
    saved = summarize(encode(report, observation, expected_contract_hash=expected))
    if change == "target":
        report["snapshot"]["form_url"] = "https://other.example/contact"
    if change == "draft":
        report["snapshot"]["rows"][0]["values"] = ["Changed"]
    if change == "scope":
        report["snapshot"]["project_id"] = "other"
    if change == "order":
        observation["cf7_static"]["contract_evidence"]["dom_order"].reverse()
    if change == "version":
        observation["cf7_static"]["contract_evidence"]["plugin_version"] = "6.1.4"
    if change == "expired":
        report["review_expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
    if change == "approval":
        saved["execution_allowed"] = True
    if change == "wire":
        saved["wire_sha256"] = "0" * 64
    with pytest.raises(PlanError):
        validate_saved(saved, report, observation, expected_contract_hash=expected)


def test_fresh_rehashed_changes_still_require_expected_contract_and_wire_limit():
    report, observation = fixture()
    expected = preview(report, observation)["contract_hash"]
    report["snapshot"]["rows"][0]["values"] = ["Changed"]
    report["snapshot_hash"] = digest(report["snapshot"])
    with pytest.raises(PlanError):
        encode(report, observation, expected_contract_hash=expected)
    oversized = deepcopy(report)
    oversized["snapshot"]["rows"][0]["values"] = ["あ" * 30000]
    oversized["snapshot_hash"] = digest(oversized["snapshot"])
    with pytest.raises(PlanError):
        encode(
            oversized,
            observation,
            expected_contract_hash=preview(oversized, observation)["contract_hash"],
        )


def test_crlf_expansion_over_wire_limit_is_rejected_even_below_input_budget():
    report, observation = fixture()
    report["snapshot"]["rows"][0]["values"] = ["a" + "\n" * 19998]
    report["snapshot"]["rows"].append(
        {
            "name": "extra",
            "field_type": "text",
            "required": True,
            "state": "UNAPPROVED_DRAFT_VALUE",
            "values": ["b" + "\n" * 19900],
        }
    )
    evidence = observation["cf7_static"]["contract_evidence"]
    evidence["controls"].append(
        {"name": "extra", "kind": "text", "required": True, "checkbox_value": ""}
    )
    evidence["dom_order"].append("extra")
    report["snapshot"]["observation_hash"] = digest(observation)
    report["snapshot_hash"] = digest(report["snapshot"])
    assert sum(len(v.encode()) for row in report["snapshot"]["rows"] for v in row["values"]) < 40000
    with pytest.raises(PlanError, match="Multipart too large"):
        encode(
            report,
            observation,
            expected_contract_hash=preview(report, observation)["contract_hash"],
        )
