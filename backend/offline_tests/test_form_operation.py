import pytest

from offline_replay.form_operation import classify, summarize


@pytest.mark.parametrize("block", ["SALES_PROHIBITED", "SUPPRESSED", "DELIVERY_UNKNOWN"])
def test_technical_candidate_never_overrides_block(block):
    result = classify({"form_status": "REVIEW_REQUIRED", "confirmation_page": True}, {block})
    assert result["operation_status"] == "BROWSER_CANDIDATE"
    assert result["sales_authorization"] == "PROHIBITED"
    assert not result["execution_allowed"]


def test_captcha_and_unknown_do_not_become_browser_verified():
    assert (
        classify({"captcha_type": "CAPTCHA_RECAPTCHA"}, set())["operation_status"]
        == "HUMAN_REQUIRED"
    )
    for status in (None, "ERROR", "UNANALYZED"):
        assert classify({"form_status": status}, set())["operation_status"] == "TECHNICAL_UNKNOWN"
    assert (
        classify({"form_status": "REVIEW_REQUIRED", "delivery_supported": False}, set())[
            "operation_status"
        ]
        == "TECHNICAL_UNKNOWN"
    )


def test_http_readiness_requires_current_structure_and_cannot_approve():
    profile = {
        "form_status": "READY",
        "delivery_supported": True,
        "sales_contact_status": "ALLOWED",
    }
    assert classify(profile, set())["operation_status"] == "TECHNICAL_UNKNOWN"
    profile |= {"structure_current": True, "method_is_post": True, "confirmed": True}
    result = classify(profile, set())
    assert result["operation_status"] == "HTTP_READY"
    assert result["sales_authorization"] == "REVIEW_REQUIRED"
    assert not result["human_approved"] and not result["execution_allowed"]
    assert classify(profile, {"IDENTITY_UNCERTAIN"})["sales_authorization"] == "UNKNOWN"


def test_summary_never_exports_private_values_or_assessment_authority():
    rows = [
        {
            "company": {"company_name": "PRIVATE", "email": "private@example.com"},
            "assessment": {
                "status": "HOLD",
                "execution_allowed": True,
                "reasons": [{"code": "IDENTITY_UNCERTAIN"}],
            },
            "forms": [{"form_status": "REVIEW_REQUIRED", "confirmation_page": True}],
        }
    ]
    result = summarize(rows)
    assert result["records"] == 1 and result["browser_verified"] == 0
    assert result["real_form_success_rate"] is None
    assert "PRIVATE" not in str(result) and "private@example.com" not in str(result)
    assert not result["rows"][0]["execution_allowed"]


def test_multiple_forms_are_not_collapsed_to_first_form_capability():
    result = summarize([{"forms": [{"confirmation_page": True}, {"form_status": "READY"}]}])
    assert result["rows"][0]["operation_status"] == "TECHNICAL_UNKNOWN"
