"""Offline explicit-choice validation; no website requests or delivery."""

import pytest

from app.services.form_intelligence.contact_method import (
    contact_method_channel,
    contact_method_review_reason,
    sender_contact_review_reason,
)


def method(**changes):
    return {
        "mapped_key": "contact_method",
        "field_type": "radio",
        "required": True,
        "decision_source": "MANUAL",
        "recommended_value": "m",
        "options": [{"value": "m", "label": "メール"}, {"value": "t", "label": "電話"}],
    } | changes


@pytest.mark.parametrize("value,channel", [("m", "email"), ("t", "phone")])
def test_selection_preserves_actual_value(value, channel):
    field = method(recommended_value=value)
    assert contact_method_channel(field["options"], value) == channel
    assert not contact_method_review_reason(field)


@pytest.mark.parametrize(
    "changes",
    [
        {"recommended_value": ""},
        {"recommended_value": "missing"},
        {"decision_source": "OPENAI"},
        {"decision_source": "RULE"},
        {"field_type": "checkbox"},
        {"options": [{"value": "m", "label": "任意"}]},
        {"options": [{"value": "email", "label": "郵送"}], "recommended_value": "email"},
        {"options": [{"value": "m", "label": "メール"}, {"value": "m", "label": "電話"}]},
        {"options": [{"value": "email", "label": "電話"}], "recommended_value": "email"},
    ],
)
def test_uncertain_or_nonhuman_selection_stops(changes):
    assert contact_method_review_reason(method(**changes))


def test_optional_unselected_method_does_not_invent_choice():
    assert contact_method_review_reason(method(required=False, recommended_value=""))


@pytest.mark.parametrize(
    "value,sources", [("m", {"phone": "0123"}), ("t", {"email": "sender@example.com"})]
)
def test_missing_selected_sender_channel_stops(value, sources):
    assert sender_contact_review_reason([method(recommended_value=value)], sources)


def test_sender_email_does_not_replace_method_value():
    field = method()
    assert not sender_contact_review_reason([field], {"email": "sender@example.com"})
    assert field["recommended_value"] == "m"
