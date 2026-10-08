import copy

import pytest

from app.services.form_saved_choice_structure import inventory


def fields():
    return [
        {
            "id": "field-a",
            "position": 0,
            "name": "services[]",
            "selector": "input",
            "label": "事業内容",
            "field_type": "checkbox",
            "required": True,
            "mapped_key": "unknown",
            "recommended_value": "OEM",
            "options": [{"label": "SNS運用", "value": "SNS"}, {"label": "OEM", "value": "OEM"}],
        }
    ]


def test_aggregated_options_are_read_only_and_never_inherit_recommendation():
    source = fields()
    before = copy.deepcopy(source)
    result = inventory(source, "a" * 64)
    assert source == before
    group = result["groups"][0]
    assert [o["value"] for o in group["options"]] == ["SNS", "OEM"]
    assert not group["rule_confirmed"] and not group["selection_confirmed"]
    assert not group["execution_allowed"] and not result["eligible_for_approval"]
    assert "recommended_value" not in group and "selected" not in group


@pytest.mark.parametrize(
    "key,value",
    [
        ("label", "Changed"),
        ("name", "changed[]"),
        ("required", False),
        ("position", 9),
        ("selector", "changed"),
    ],
)
def test_evidence_changes_invalidate_hash(key, value):
    original = fields()
    changed = copy.deepcopy(original)
    changed[0][key] = value
    assert (
        inventory(original, "a" * 64)["source_hash"] != inventory(changed, "a" * 64)["source_hash"]
    )


def test_option_order_value_and_fingerprint_are_bound():
    original = fields()
    changed = copy.deepcopy(original)
    changed[0]["options"].reverse()
    assert (
        inventory(original, "a" * 64)["source_hash"] != inventory(changed, "a" * 64)["source_hash"]
    )
    changed[0]["options"][0]["value"] = "NEW"
    assert (
        inventory(original, "a" * 64)["source_hash"] != inventory(changed, "a" * 64)["source_hash"]
    )
    assert (
        inventory(original, "a" * 64)["source_hash"] != inventory(original, "b" * 64)["source_hash"]
    )


def test_repeated_fields_duplicate_values_and_consent_stay_unconfirmed():
    original = fields()
    original.append(copy.deepcopy(original[0]))
    original[1].update(id="field-b", position=1, mapped_key="privacy_consent")
    group = inventory(original, "a" * 64)["groups"][0]
    assert len(group["options"]) == 4
    assert {"AMBIGUOUS_VALUES", "CONSENT_REVIEW_REQUIRED", "REPEATED_SAVED_FIELDS"} <= set(
        group["warnings"]
    )
    assert not group["selection_confirmed"]


@pytest.mark.parametrize("options", [None, {}, 7, [None], [{"value": None}], [{"value": ""}]])
def test_missing_or_malformed_options_are_unknown(options):
    original = fields()
    original[0]["options"] = options
    assert "INCOMPLETE_OPTIONS" in inventory(original, "a" * 64)["groups"][0]["warnings"]


def test_hidden_values_are_not_exposed_and_empty_inventory_is_valid():
    source = fields() + [
        {"field_type": "hidden", "name": "secret", "options": [{"value": "PRIVATE"}]}
    ]
    assert "PRIVATE" not in str(inventory(source, "a" * 64))
    assert inventory([], "")["groups"] == []


def test_valid_options_do_not_hide_missing_entries():
    source = fields()
    source[0]["options"].append(None)
    group = inventory(source, "a" * 64)["groups"][0]
    assert "INCOMPLETE_OPTIONS" in group["warnings"]
    assert not group["eligible_for_approval"]
