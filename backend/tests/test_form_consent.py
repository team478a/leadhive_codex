"""Consent inference and preparation safety with anonymous, offline examples."""

from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from app.services.form_delivery import _parse_form
from app.services.form_intelligence.consent import consent_review_reason
from app.services.form_intelligence.fields import mapping_review_reason, parse_form_fields


def consent(**changes):
    return {
        "mapped_key": "privacy_consent",
        "field_type": "checkbox",
        "required": True,
        "label": "プライバシーに同意",
        "decision_source": "MANUAL",
        "recommended_value": "yes",
        "options": [{"value": "yes", "label": "プライバシーに同意"}],
    } | changes


@pytest.mark.parametrize(
    "changes",
    [
        {"decision_source": "RULE"},
        {"decision_source": "OPENAI"},
        {"recommended_value": ""},
        {"recommended_value": "wrong"},
        {"field_type": "select"},
        {"options": []},
        {"options": [{"value": "", "label": "プライバシーに同意"}]},
        {"options": [{"value": "yes", "label": "同意しない"}]},
        {"label": "個人情報とメルマガ登録に同意"},
        {"options": [{"value": "yes", "label": "同意"}, {"value": "yes", "label": "別条件"}]},
    ],
)
def test_uncertain_consent_stops(changes):
    assert consent_review_reason(consent(**changes))


def test_valid_human_choice_and_optional_optout():
    assert not consent_review_reason(consent())
    assert not consent_review_reason(
        consent(
            mapped_key="newsletter_consent",
            label="メルマガ登録",
            required=False,
            recommended_value="",
            options=[{"value": "yes", "label": "メルマガ希望"}],
        )
    )


@pytest.mark.parametrize(
    "attribute,expected", [("", "on"), ('value=""', ""), ('value="accepted"', "accepted")]
)
def test_checkbox_default_value_is_distinct_from_explicit_empty(attribute, expected):
    form = BeautifulSoup(
        f'<form><label>プライバシーに同意<input type="checkbox" name="privacy" {attribute}'
        " required></label></form>",
        "html.parser",
    ).form
    field = parse_form_fields(form)[0]
    assert field["options"][0]["value"] == expected
    assert field["required"] and field["mapped_key"] == "privacy_consent"
    assert field["recommended_value"] == ""


def test_cf7_inverted_acceptance_remains_unresolved():
    form = BeautifulSoup(
        '<form><span class="wpcf7-acceptance optional invert"><label>プライバシー'
        '<input type="checkbox" name="privacy" value="yes"></label></span></form>',
        "html.parser",
    ).form
    field = parse_form_fields(form)[0]
    assert not field["required"]
    assert consent_review_reason(field)


@pytest.mark.parametrize("optional,unknown", [("", True), (" 任意", False)])
def test_missing_required_attribute_does_not_prove_optional(optional, unknown):
    form = BeautifulSoup(
        f"<form><label>プライバシーに同意{optional}"
        '<input type="checkbox" name="privacy" value="yes"></label>'
        '<textarea name="your-message"></textarea></form>',
        "html.parser",
    ).form
    fields = parse_form_fields(form)
    fields[0].update(decision_source="MANUAL", recommended_value="")
    assert ("必須性未確認" in fields[0]["label"]) == unknown
    assert bool(mapping_review_reason(fields)) == unknown


@pytest.mark.parametrize(
    "source,value,expected", [("RULE", "yes", ""), ("MANUAL", "", ""), ("MANUAL", "yes", "yes")]
)
def test_prechecked_newsletter_does_not_replace_human_choice(source, value, expected):
    html = (
        '<form method="post"><label>メルマガ登録<input type="checkbox" name="newsletter"'
        ' value="yes" checked></label><textarea name="message"></textarea>'
        "<button>送信</button></form>"
    )
    metadata = SimpleNamespace(
        name="newsletter",
        mapped_key="newsletter_consent",
        decision_source=source,
        recommended_value=value,
        required=False,
        confidence=1.0,
    )
    field = _parse_form(html, "https://fixture.example/contact", profile_fields=[metadata]).fields[
        0
    ]
    assert field.value == expected
