from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.schema_form_review import FormInputReviewInput
from app.services.form_input_preparation import prepare


def inputs():
    fields = [
        {"name": "body", "position": 0, "field_type": "textarea"},
        {"name": "email", "position": 1, "field_type": "email"},
    ]
    material = {
        "technical_diagnostic": {"boundary": "TECHNICAL_HOLD", "route": "CF7_CANDIDATE"},
        "profile_id": "profile",
        "project_id": "project",
        "company_id": "company",
        "form_url": "https://example.com/contact",
        "profile_fingerprint": "f" * 64,
        "draft_id": "draft",
        "draft_hash": "d" * 64,
        "items": [
            {
                "position": i,
                "name": f["name"],
                "label": f["name"],
                "required": True,
                "review_state": "UNAPPROVED_DRAFT_VALUE" if i == 0 else "SENDER_VALUE_PROPOSED",
                "proposed_value": "Draft" if i == 0 else "sender@example.com",
            }
            for i, f in enumerate(fields)
        ],
    }
    observation = {
        "freshness": "CURRENT",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "structure_status": "SAME_STRUCTURE",
        "method_is_post": True,
        "cf7_static": {
            "status": "CF7_CANDIDATE",
            "version": "6.2",
            "rest_link_same_origin": True,
            "base_override": False,
            "file_inputs": 0,
            "missing_names": 0,
            "unsupported_controls": 0,
            "contract_shape": {
                "review_hidden_shape_valid": True,
                **dict.fromkeys(
                    (
                        "extra_hidden",
                        "invalid_names",
                        "repeated_names",
                        "radio_controls",
                        "select_controls",
                        "disabled_controls",
                    ),
                    0,
                ),
            },
        },
    }
    return material, fields, observation


def test_snapshot_is_stable_and_never_authorizes():
    m, f, o = inputs()
    report = prepare(m, f, o, source_hash="s")
    assert (
        report["can_record"]
        and report["snapshot_hash"] == prepare(m, f, o, source_hash="s")["snapshot_hash"]
    )
    assert not report["execution_allowed"] and not report["eligible_for_approval"]
    assert not report["live_fetch_performed"]
    assert report["snapshot_hash"] != prepare(m, f, o, source_hash="changed")["snapshot_hash"]
    revised = deepcopy(m)
    revised["items"][0]["proposed_value"] = "Changed draft"
    assert report["snapshot_hash"] != prepare(revised, f, o, source_hash="s")["snapshot_hash"]


def test_consent_requires_explicit_manual_value_and_valid_option():
    m, f, o = inputs()
    f.append(
        {
            "name": "consent",
            "position": 2,
            "field_type": "checkbox",
            "required": True,
            "options": [{"value": "yes"}],
            "recommended_value": "yes",
            "decision_source": "RULE",
        }
    )
    m["items"].append(
        {
            "name": "consent",
            "position": 2,
            "label": "同意",
            "required": True,
            "review_state": "HUMAN_CONSENT_REQUIRED",
            "proposed_value": None,
        }
    )
    assert not prepare(m, f, o, source_hash="s")["can_record"]
    f[-1]["decision_source"] = "MANUAL"
    result = prepare(m, f, o, source_hash="s")
    assert result["can_record"] and result["snapshot"]["rows"][-1]["values"] == ["yes"]
    f[-1]["recommended_value"] = "unknown"
    assert not prepare(m, f, o, source_hash="s")["can_record"]


@pytest.mark.parametrize(
    "case",
    [
        "block",
        "captcha",
        "stale",
        "expired",
        "missing_expiry",
        "shape",
        "extra_hidden",
        "version",
        "draft",
        "value",
        "choice",
        "duplicate",
    ],
)
def test_missing_unsafe_or_unconfirmed_values_cannot_record(case):
    m, f, o = inputs()
    if case == "block":
        m["technical_diagnostic"]["boundary"] = "BLOCKED"
    elif case == "captcha":
        o["captcha_state"] = "DETECTED"
    elif case == "stale":
        o["freshness"] = "SOURCE_CHANGED"
    elif case == "expired":
        o["expires_at"] = "2020-01-01T00:00:00+00:00"
    elif case == "missing_expiry":
        o.pop("expires_at")
    elif case == "shape":
        o["cf7_static"]["contract_shape"].pop("review_hidden_shape_valid")
    elif case == "extra_hidden":
        o["cf7_static"]["contract_shape"]["extra_hidden"] = 1
    elif case == "version":
        o["cf7_static"]["version"] = "6.2.1"
    elif case == "draft":
        m["draft_id"] = None
    elif case == "value":
        m["items"][0]["proposed_value"] = None
    elif case == "choice":
        m["items"][0]["review_state"] = "HUMAN_CONSENT_REQUIRED"
    else:
        f.append(deepcopy(f[0]))
    report = prepare(m, f, o, source_hash="s")
    assert not report["can_record"] and report["reasons"]


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_explicit_confirmation_requires_strict_true(value):
    with pytest.raises(ValueError):
        FormInputReviewInput(expected_snapshot_hash="f" * 64, input_content_confirmed=value)
