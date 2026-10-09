import json

import pytest

from app.services.cf7_readiness import summarize
from app.services.form_adapter_prerequisites import assess
from tests.test_form_adapter_prerequisites import diagnostic, observation


def saved(**changes):
    value = observation()
    value["cf7_static"].update(
        version="6.2",
        rest_link_same_origin=True,
        file_inputs=0,
        missing_names=0,
        unsupported_controls=0,
    )
    return value | changes


def test_lab_62_never_becomes_real_site_ready():
    result = summarize(diagnostic(core_permission_status="ALLOWED"), saved(), [])
    assert result["status"] == "HOLD"
    assert result["primary_reason"] == "LEGACY_PREPARATION_UNSUPPORTED"
    assert result["lab_contract_status"] == "VERIFIED_FIXTURE_ONLY"
    assert result["version_evidence"] == "HTML_MARKER_ONLY"
    assert not result["execution_allowed"] and not result["eligible_for_approval"]
    assert not result["live_fetch_performed"]
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize(
    "changes,code,status",
    [
        ({"sales_prohibition_detected": True}, "SALES_PROHIBITED", "BLOCKED"),
        ({"captcha_state": "DETECTED"}, "CAPTCHA", "HUMAN_REQUIRED"),
        ({"freshness": "EXPIRED"}, "OBSERVATION_STALE", "HOLD"),
        ({"freshness": "SOURCE_CHANGED"}, "OBSERVATION_STALE", "HOLD"),
        ({"structure_status": "CHANGED"}, "STRUCTURE_UNVERIFIED", "HOLD"),
        ({"cf7_static": None}, "STATIC_UNVERIFIED", "HOLD"),
        ({"cf7_static": "SECRET"}, "STATIC_UNVERIFIED", "HOLD"),
    ],
)
def test_priority_and_unknowns(changes, code, status):
    result = summarize(diagnostic(core_permission_status="ALLOWED"), saved(**changes), [])
    assert result["status"] == status
    assert result["primary_reason"] == code
    assert not result["execution_allowed"]


def test_hard_block_wins_over_captcha_and_technical_facts():
    result = summarize(
        diagnostic(boundary="BLOCKED"),
        saved(captcha_state="DETECTED", sales_prohibition_detected=True),
        [],
    )
    assert result["status"] == "BLOCKED" and result["primary_reason"] == "CONTACT_BLOCKED"


@pytest.mark.parametrize("version", ["6.1.4", "6.1.6", "6.1.7", "6.2", "6.2.1", None, "SECRET"])
def test_exact_versions_only_and_no_raw_output(version):
    value = saved()
    value["cf7_static"]["version"] = version
    result = summarize(diagnostic(), value, [])
    assert result["lab_contract_status"] == (
        "VERIFIED_FIXTURE_ONLY" if version in ("6.1.4", "6.1.6", "6.2") else "UNVERIFIED"
    )
    assert "SECRET" not in json.dumps(result)
    assert result["status"] == "HOLD"


@pytest.mark.parametrize("state,status", [("UNKNOWN", "HOLD"), ("DETECTED", "HUMAN_REQUIRED")])
def test_616_fixture_contract_does_not_enable_saved_site_preparation(state, status):
    value = saved(captcha_state=state)
    value["cf7_static"].update(version="6.1.6")
    value["cf7_static"]["contract_shape"].update(
        reviewed_lab_version=False, hidden_shape_valid=False, extra_hidden=1
    )
    result = summarize(diagnostic(core_permission_status="ALLOWED"), value, [])
    assert result["observed_version"] == "6.1.6"
    assert result["lab_contract_status"] == "VERIFIED_FIXTURE_ONLY"
    assert result["status"] == status
    assert {
        "LEGACY_PREPARATION_UNSUPPORTED",
        "CONTRACT_SHAPE_REVIEW",
        "REAL_SITE_ADAPTER_UNCONNECTED",
    } <= {reason["code"] for reason in result["reasons"]}
    assert not result["execution_allowed"] and not result["eligible_for_approval"]


def test_616_marker_in_size_limited_inspection_is_not_lab_evidence():
    value = saved()
    value["cf7_static"].update(status="LIMIT_EXCEEDED", version="6.1.6")
    result = summarize(diagnostic(), value, [])
    assert result["observed_version"] is None
    assert result["lab_contract_status"] == "UNVERIFIED"
    assert result["status"] == "HOLD" and not result["execution_allowed"]


def test_technical_reasons_and_choice_review():
    value = saved()
    value["cf7_static"].update(
        file_inputs=1,
        missing_names=1,
        unsupported_controls=1,
        base_override=True,
        rest_link_same_origin=False,
    )
    result = assess(diagnostic(), value, [{"review_current": False}])["cf7_readiness"]
    codes = {r["code"] for r in result["reasons"]}
    assert {
        "FILE_UNSUPPORTED",
        "FIELD_NAMES_MISSING",
        "CONTROL_UNSUPPORTED",
        "BASE_OVERRIDE",
        "REST_ROOT_UNVERIFIED",
        "CHOICE_REVIEW_REQUIRED",
    } <= codes
    assert not result["live_fetch_performed"]


def test_non_cf7_is_not_mislabeled():
    result = summarize(diagnostic(route="NATIVE_CANDIDATE", boundary="HUMAN_REQUIRED"), saved(), [])
    assert result["status"] == "NOT_APPLICABLE"
