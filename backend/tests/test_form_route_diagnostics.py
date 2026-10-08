import pytest

from app.models import FormProfile
from app.services.form_route_diagnostics import diagnose


def profile(**changes):
    return FormProfile(
        **(
            dict(
                form_status="REVIEW_REQUIRED",
                sales_contact_status="UNCERTAIN",
                captcha_type="CAPTCHA_NONE",
                delivery_supported=False,
                confirmation_page=False,
            )
            | changes
        )
    )


def report(p=None, fields=None, observation=None, **kwargs):
    return diagnose(
        p or profile(),
        fields or [],
        observation,
        permission_status=kwargs.pop("permission_status", "UNCERTAIN"),
        permission_reason=kwargs.pop("permission_reason", "not_checked"),
        **kwargs,
    )


def test_cf7_marker_is_only_a_candidate_and_tokens_are_not_exposed():
    result = report(
        fields=[{"name": "_wpcf7", "field_type": "hidden", "recommended_value": "SECRET_TOKEN"}]
    )
    assert result["route"] == "CF7_CANDIDATE" and result["boundary"] == "TECHNICAL_HOLD"
    assert (
        not result["execution_allowed"]
        and not result["human_approved"]
        and not result["live_fetch_performed"]
    )
    assert "SECRET_TOKEN" not in str(result)


@pytest.mark.parametrize(
    "freshness,method",
    [("CURRENT", False), ("EXPIRED", None), ("SOURCE_CHANGED", None), ("INVALID", None)],
)
def test_observation_freshness_never_promotes_old_method(freshness, method):
    result = report(
        observation={
            "freshness": freshness,
            "method_is_post": False,
            "structure_status": "UNSUPPORTED_METHOD",
        }
    )
    assert result["observed_method_is_post"] is method
    assert result["route"] == ("BROWSER_REVIEW" if freshness == "CURRENT" else "UNKNOWN")
    assert not result["execution_allowed"]


def test_missing_names_are_counted_only_for_visible_inputs():
    result = report(
        fields=[
            {"name": "", "field_type": "hidden"},
            {"name": "", "field_type": "text"},
            {"name": "", "field_type": "textarea"},
        ]
    )
    assert result["missing_field_names"] == 2
    assert result["route"] == "BROWSER_REVIEW"
    assert "REQUIRED_FIELD_UNKNOWN" in [r["code"] for r in result["reasons"]]


@pytest.mark.parametrize("kind", ["permission", "profile", "do_not_contact", "unknown_result"])
def test_blocks_dominate_candidate_and_captcha(kind):
    p = profile(delivery_supported=True, captcha_type="CAPTCHA_RECAPTCHA")
    kwargs = {}
    if kind == "profile":
        p.form_status = "BLOCKED"
    elif kind == "do_not_contact":
        kwargs["do_not_contact"] = True
    else:
        kwargs["permission_status"] = "PROHIBITED"
        if kind == "unknown_result":
            kwargs["permission_reason"] = "form_result_unknown"
    result = report(p, **kwargs)
    assert result["boundary"] == "BLOCKED" and not result["execution_allowed"]
    if kind == "unknown_result":
        assert result["reasons"][0]["code"] == "DELIVERY_UNKNOWN"
        assert "自動再送せず" in result["reasons"][0]["message"]


def test_captcha_requires_human_and_native_candidate_is_never_authorized():
    result = report(profile(delivery_supported=True, captcha_type="CAPTCHA_HCAPTCHA"))
    assert result["boundary"] == "HUMAN_REQUIRED"
    result = report(
        profile(delivery_supported=True),
        observation={
            "freshness": "CURRENT",
            "method_is_post": True,
            "structure_status": "SAME_STRUCTURE",
        },
        permission_status="ALLOWED",
    )
    assert result["route"] == "NATIVE_CANDIDATE" and result["boundary"] == "HUMAN_REVIEW"
    assert not result["execution_allowed"] and not result["human_approved"]


def test_confirmation_and_failed_current_observation_are_not_success():
    result = report(
        profile(delivery_supported=True, confirmation_page=True),
        observation={"freshness": "CURRENT", "structure_status": "FETCH_FAILED"},
    )
    assert result["boundary"] == "TECHNICAL_HOLD"
    assert "FORM_ANALYSIS_STALE" in [r["code"] for r in result["reasons"]]


def test_native_flag_without_current_observation_remains_technical_hold():
    for observation in (None, {"freshness": "EXPIRED", "method_is_post": True}):
        result = report(
            profile(delivery_supported=True), observation=observation, permission_status="ALLOWED"
        )
        assert result["boundary"] == "TECHNICAL_HOLD"
        assert not result["execution_allowed"]
