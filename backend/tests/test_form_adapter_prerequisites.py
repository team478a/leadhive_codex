import pytest

from app.services.form_adapter_prerequisites import assess


def diagnostic(**changes):
    return {
        "boundary": "TECHNICAL_HOLD",
        "route": "CF7_CANDIDATE",
        "core_permission_status": "UNCERTAIN",
        "missing_field_names": 0,
        "saved_delivery_supported": False,
        "next_action": "禁止維持",
    } | changes


def checked_shape(**changes):
    return {
        "reviewed_lab_version": True,
        "hidden_complete": True,
        "hidden_shape_valid": True,
        "extra_hidden": 0,
        "invalid_names": 0,
        "repeated_names": 0,
        "radio_controls": 0,
        "select_controls": 0,
        "disabled_controls": 0,
        "checkbox_controls": 0,
    } | changes


def observation(shape=None, **changes):
    return {
        "freshness": "CURRENT",
        "structure_status": "SAME_STRUCTURE",
        "method_is_post": True,
        "cf7_static": {
            "status": "CF7_CANDIDATE",
            "contract_shape": shape or checked_shape(),
            "hidden": "SECRET",
        },
    } | changes


def check(result, code):
    return next(c for c in result["checks"] if c["code"] == code)


@pytest.mark.parametrize(
    "static", [None, "malformed", {"status": "PARSE_FAILED", "contract_shape": checked_shape()}]
)
def test_unparsed_shape_is_unknown(static):
    result = assess(diagnostic(), observation(cf7_static=static), [])
    assert result["cf7_shape_issues"] == ["STATIC_SHAPE_UNVERIFIED"]


def test_even_complete_saved_evidence_cannot_authorize_execution():
    result = assess(
        diagnostic(core_permission_status="ALLOWED"), observation(), [{"review_current": True}]
    )
    assert check(result, "CHOICE_REVIEW")["status"] == "OBSERVED"
    assert check(result, "CF7_CONTRACT_SHAPE")["status"] == "OBSERVED"
    assert check(result, "EXECUTION_ROUTE")["status"] == "UNSUPPORTED"
    assert check(result, "HUMAN_APPROVAL")["status"] == "SEPARATE_REVIEW"
    assert not result["execution_allowed"] and not result["eligible_for_approval"]
    assert not result["live_fetch_performed"] and "SECRET" not in str(result)


@pytest.mark.parametrize("freshness", ["EXPIRED", "SOURCE_CHANGED", "INVALID", "NOT_CHECKED"])
def test_old_observation_cannot_satisfy_shape_or_structure(freshness):
    result = assess(diagnostic(), observation(freshness=freshness), [])
    assert check(result, "STRUCTURE_COMPARISON")["status"] == "REVIEW"
    assert result["cf7_shape_issues"] == ["STATIC_SHAPE_UNVERIFIED"]


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"radio_controls": 1}, "RADIO_UNSUPPORTED"),
        ({"extra_hidden": 1}, "EXTRA_HIDDEN"),
        ({"checkbox_controls": 2}, "CHECKBOX_CONTRACT_UNCONNECTED"),
        ({"reviewed_lab_version": False}, "VERSION_UNVERIFIED"),
        ({"repeated_names": 3}, "REPEATED_NAMES"),
        ({"extra_hidden": True}, "STATIC_SHAPE_UNVERIFIED"),
        ({"extra_hidden": -1}, "STATIC_SHAPE_UNVERIFIED"),
        ({"hidden_shape_valid": "true"}, "HIDDEN_SHAPE_UNVERIFIED"),
    ],
)
def test_contract_gaps_and_unknowns_are_not_success(changes, reason):
    result = assess(diagnostic(), observation(checked_shape(**changes)), [])
    assert reason in result["cf7_shape_issues"]
    assert check(result, "CF7_CONTRACT_SHAPE")["status"] == "REVIEW"


def test_blocks_captcha_reviews_and_no_cf7():
    result = assess(diagnostic(boundary="BLOCKED"), None, [{"review_current": False}])
    assert check(result, "CONTACT_PERMISSION")["status"] == "BLOCKED"
    assert result["next_action"] == "禁止維持"
    result = assess(diagnostic(boundary="HUMAN_REQUIRED"), None, [])
    assert check(result, "EXECUTION_ROUTE")["status"] == "HUMAN_REQUIRED"
    result = assess(
        diagnostic(route="NATIVE_CANDIDATE", saved_delivery_supported=True), observation(), []
    )
    assert check(result, "CF7_CONTRACT_SHAPE")["status"] == "NOT_APPLICABLE"
    assert check(result, "CHOICE_REVIEW")["status"] == "NOT_APPLICABLE"
    assert check(result, "EXECUTION_ROUTE")["status"] == "SEPARATE_REVIEW"
    assert not result["execution_allowed"]
