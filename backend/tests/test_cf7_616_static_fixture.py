"""6.1.6 managed HTML observations only; no version/dispatch allowlist expansion."""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.services.cf7_candidate_contract import CF7Candidate
from app.services.cf7_readiness import summarize
from app.services.cf7_static_inspection import inspect_isolated
from app.services.form_intelligence.analyzer import _captcha_type
from app.services.form_intelligence.compatibility import assess_delivery_compatibility
from tests.test_cf7_candidate_contract import candidate

URL = "https://managed.example/contact/"
HTML = (Path(__file__).parent / "fixtures" / "cf7-616-managed.html").read_text(encoding="utf-8")


def triage(markup=HTML):
    static = inspect_isolated(markup, URL, 0)
    captcha = _captcha_type(markup)
    return static, summarize(
        {
            "route": "CF7_CANDIDATE",
            "boundary": "HUMAN_REQUIRED" if captcha != "CAPTCHA_NONE" else "REVIEW",
            "core_permission_status": "UNCERTAIN",
        },
        {
            "cf7_static": static,
            "freshness": "STALE",
            "structure_status": "UNVERIFIED",
            "captcha_state": "DETECTED" if captcha != "CAPTCHA_NONE" else "UNKNOWN",
        },
        [],
    )


def test_616_marker_is_observed_without_legacy_contract_or_authority():
    static, readiness = triage()
    assert static["status"] == "CF7_CANDIDATE"
    assert static["version"] == "6.1.6"
    assert static["markers_complete"] and static["form_id_valid"]
    assert static["rest_link_same_origin"] and static["method_is_post"]
    shape = static["contract_shape"]
    assert shape["hidden_complete"] and shape["extra_hidden"] == 0
    assert not shape["reviewed_lab_version"]
    assert not shape["hidden_shape_valid"] and not shape["review_hidden_shape_valid"]
    assert static["contract_evidence"] is None
    assert readiness["status"] == "HOLD"
    codes = {reason["code"] for reason in readiness["reasons"]}
    assert {
        "LEGACY_PREPARATION_UNSUPPORTED",
        "CONTACT_PERMISSION_REVIEW",
        "REAL_SITE_ADAPTER_UNCONNECTED",
    } <= codes
    for result in (static, readiness):
        assert not result["execution_allowed"] and not result["eligible_for_approval"]


@pytest.mark.parametrize("name", ["_wpcf7_recaptcha_response", "_wpnonce", "unknown-token"])
def test_unknown_hidden_is_counted_not_exposed_or_authorized(name):
    markup = HTML.replace(
        "</fieldset>", f'<input type="hidden" name="{name}" value="PRIVATE-TOKEN"></fieldset>'
    )
    static, readiness = triage(markup)
    assert static["contract_shape"]["extra_hidden"] == 1
    assert static["contract_evidence"] is None
    assert "PRIVATE-TOKEN" not in json.dumps(static)
    assert readiness["status"] in {"HOLD", "HUMAN_REQUIRED"}
    assert not readiness["execution_allowed"]


def test_recaptcha_is_human_required_even_with_empty_token():
    markup = HTML.replace(
        "</fieldset>", '<input type="hidden" name="_wpcf7_recaptcha_response" value=""></fieldset>'
    )
    _, readiness = triage(markup)
    assert readiness["status"] == "HUMAN_REQUIRED"
    assert "CAPTCHA" in {r["code"] for r in readiness["reasons"]}
    assert not readiness["eligible_for_approval"]


@pytest.mark.parametrize(
    "old,new,key,expected",
    [
        (
            "https://managed.example/wp-json/",
            "https://other.example/wp-json/",
            "rest_link_same_origin",
            False,
        ),
        ("</head>", '<base href="https://other.example/"> </head>', "base_override", True),
        ("</form>", '<input type="file" name="attachment"></form>', "file_inputs", 1),
        ('method="post"', 'method="get"', "method_is_post", False),
        ('name="your-name"', "", "missing_names", 1),
    ],
)
def test_unsafe_or_unsupported_shape_stays_non_executable(old, new, key, expected):
    static, readiness = triage(HTML.replace(old, new))
    assert static[key] == expected
    assert static["contract_evidence"] is None
    assert not static["execution_allowed"] and not readiness["execution_allowed"]


def test_duplicate_hidden_and_oversized_input_fail_closed():
    duplicate = HTML.replace(
        "</fieldset>", '<input type="hidden" name="_wpcf7" value="8"></fieldset>'
    )
    assert inspect_isolated(duplicate, URL, 0)["status"] == "PARSE_FAILED"
    oversized = HTML + " " * 262145
    assert inspect_isolated(oversized, URL, 0)["status"] == "LIMIT_EXCEEDED"


def test_existing_candidate_cannot_relabel_616_as_614():
    data = candidate().model_dump(mode="json")
    for hidden in data["hidden"]:
        if hidden["name"] == "_wpcf7_version":
            hidden["value"] = "6.1.6"
    with pytest.raises(ValueError):
        CF7Candidate.model_validate_json(json.dumps(data))
    data["plugin_version"] = "6.1.6"
    with pytest.raises(ValueError):
        CF7Candidate.model_validate_json(json.dumps(data))


def test_multipart_and_cf7_are_not_native_delivery_support():
    form = BeautifulSoup(HTML, "html.parser").select_one("form")
    assert form is not None
    assert not assess_delivery_compatibility(form, URL).supported
    del form.attrs["enctype"]
    result = assess_delivery_compatibility(form, URL)
    assert not result.supported and "Contact Form 7" in result.reason
