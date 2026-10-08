from copy import deepcopy

import pytest

from app.services.form_intelligence.fields import GROUP_REVIEW_MARKER
from app.services.form_review_material import build_review_material


def field(**changes):
    return (
        dict(
            name="name",
            mapped_key="contact_name",
            field_type="text",
            required=True,
            label="名前",
            options=[],
            position=0,
        )
        | changes
    )


def material(fields, **changes):
    return build_review_material(
        fields,
        {"contact_name": "Test Sender", "email": "sender@example.test"},
        subject=changes.get("subject", "Draft"),
        body=changes.get("body", "Draft body"),
    )


def test_sender_and_draft_suggestions_are_not_authorized_or_truncated():
    fields = [field(), field(name="body", mapped_key="message", field_type="textarea")]
    original = deepcopy(fields)
    result = material(fields, body="x" * 3000)
    assert result["items"][0]["proposed_value"] == "Test Sender"
    assert len(result["items"][1]["proposed_value"]) == 3000
    assert (
        result["review_only"] and not result["execution_supported"] and not result["human_approved"]
    )
    assert fields == original


@pytest.mark.parametrize("key", ["privacy_consent", "newsletter_consent"])
def test_even_saved_manual_consent_is_not_automatically_selected(key):
    result = material(
        [
            field(
                mapped_key=key,
                field_type="checkbox",
                decision_source="MANUAL",
                recommended_value="yes",
                options=[{"value": "yes", "label": "同意"}],
            )
        ]
    )
    assert result["items"][0]["proposed_value"] is None
    assert result["items"][0]["review_state"] == "HUMAN_CONSENT_REQUIRED"


@pytest.mark.parametrize(
    "kind,name", [("hidden", "nonce"), ("file", "upload"), ("textarea", "_wpcf7_ak_hp_textarea")]
)
def test_hidden_file_and_legacy_honeypot_never_receive_body(kind, name):
    item = material([field(name=name, mapped_key="message", field_type=kind)])["items"][0]
    assert item["review_state"] == "DO_NOT_FILL" and item["proposed_value"] is None


def test_group_and_choice_require_human_without_using_recommended_value():
    result = material(
        [
            field(label=GROUP_REVIEW_MARKER, field_type="checkbox"),
            field(name="type", field_type="select", recommended_value="sales"),
        ]
    )
    assert result["human_review_count"] == 2
    assert all(item["proposed_value"] is None for item in result["items"])


def test_duplicate_and_unnamed_fields_are_not_guessed():
    result = material([field(), field(), field(name="")])
    assert all(i["review_state"] == "FIELD_IDENTITY_REVIEW_REQUIRED" for i in result["items"])


def test_multiple_body_and_unknown_control_are_not_filled():
    result = material(
        [
            field(name="body1", mapped_key="message", field_type="textarea"),
            field(name="body2", mapped_key="message", field_type="textarea"),
            field(name="password", mapped_key="email", field_type="password"),
        ]
    )
    assert result["human_review_count"] == 3
    assert all(i["proposed_value"] is None for i in result["items"])


def test_missing_values_unknown_fields_and_zero_items():
    result = material(
        [
            field(mapped_key="phone"),
            field(name="body", mapped_key="message"),
            field(name="other", mapped_key="unknown", recommended_value="malicious"),
            field(name="optional", mapped_key="unknown", required=False),
        ],
        body="",
    )
    assert result["missing_required_values"] == 2
    assert result["items"][2]["proposed_value"] is None
    assert result["items"][3]["review_state"] == "OPTIONAL_LEAVE_BLANK"
    empty = material([])
    assert empty["human_review_count"] == empty["missing_required_values"] == 0
    assert not empty["execution_supported"]
