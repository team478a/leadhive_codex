"""Independent review fixture; never authorizes 6.2.1 dispatch or consent."""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.services.cf7_readiness import summarize
from app.services.cf7_static_inspection import inspect_isolated
from app.services.form_intelligence.compatibility import assess_delivery_compatibility
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_review_material import build_review_material
from tests.test_cf7_62_contract import plan

URL = "https://managed.example/contact/"
HTML = (Path(__file__).parent / "fixtures" / "cf7-621-choice-review.html").read_text(
    encoding="utf-8"
)


def material(markup=HTML):
    form = BeautifulSoup(markup, "html.parser").select_one("form")
    assert form is not None
    return build_review_material(
        parse_form_fields(form),
        {
            "company_name": "Fixture Company",
            "contact_name": "Fixture Person",
            "email": "fixture@example.com",
        },
        subject="Fixture subject",
        body="Unapproved fixture body",
    )


def test_shape_is_observed_but_no_621_contract_or_authority():
    static = inspect_isolated(HTML, URL, 0)
    assert static["version"] == "6.2.1" and static["status"] == "CF7_CANDIDATE"
    shape = static["contract_shape"]
    assert (
        shape["extra_hidden"] == 4
        and shape["select_controls"] == 1
        and shape["checkbox_controls"] == 1
    )
    assert not shape["review_hidden_shape_valid"] and static["contract_evidence"] is None
    for value in ("PRIVATE-CONTEXT", "PRIVATE-ADDON", "PRIVATE-NONCE", "PRIVATE-ROUTE"):
        assert value not in json.dumps(static)
    readiness = summarize(
        {"route": "CF7_CANDIDATE", "boundary": "REVIEW", "core_permission_status": "UNCERTAIN"},
        {"cf7_static": static, "freshness": "CURRENT", "structure_status": "SAME_STRUCTURE"},
        [],
    )
    assert readiness["status"] == "HOLD" and readiness["lab_contract_status"] == "UNVERIFIED"
    assert "VERSION_UNVERIFIED" in {r["code"] for r in readiness["reasons"]}
    assert not readiness["execution_allowed"] and not readiness["eligible_for_approval"]


@pytest.mark.parametrize("defaults", [False, True])
def test_choices_and_consent_are_never_auto_selected(defaults):
    markup = HTML
    if defaults:
        markup = markup.replace('value="partnership"', 'value="partnership" selected').replace(
            'name="privacy"', 'name="privacy" checked'
        )
    result = material(markup)
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["consultation"]["review_state"] == "CHOICE_REVIEW_REQUIRED"
    assert by_name["privacy"]["review_state"] == "HUMAN_CONSENT_REQUIRED"
    assert (
        by_name["consultation"]["proposed_value"] is None
        and by_name["privacy"]["proposed_value"] is None
    )
    assert by_name["consultation"]["required"] and by_name["privacy"]["required"]
    assert len(by_name["consultation"]["options"]) == 3
    assert all(
        item["review_state"] == "DO_NOT_FILL"
        for item in result["items"]
        if item["field_type"] == "hidden"
    )
    assert "PRIVATE-" not in json.dumps(result)
    assert not result["execution_supported"] and not result["human_approved"]


def test_inverse_acceptance_remains_human_review():
    result = material(HTML.replace('class="wpcf7-acceptance"', 'class="wpcf7-acceptance invert"'))
    consent = next(item for item in result["items"] if item["name"] == "privacy")
    assert consent["review_state"] == "HUMAN_CONSENT_REQUIRED" and consent["proposed_value"] is None
    assert "未対応" in consent["options"][0]["label"]


def test_no_native_delivery_or_62_version_substitution():
    form = BeautifulSoup(HTML, "html.parser").select_one("form")
    assert form is not None and not assess_delivery_compatibility(form, URL).supported
    data = plan().model_dump(mode="json")
    data["base"]["plugin_version"] = "6.2.1"
    with pytest.raises(ValueError):
        type(plan()).model_validate(data)
    data = plan().model_dump(mode="json")
    next(h for h in data["base"]["hidden"] if h["name"] == "_wpcf7_version")["value"] = "6.2.1"
    with pytest.raises(ValueError):
        type(plan()).model_validate(data)


@pytest.mark.parametrize(
    "suffix", ['<input type="file" name="upload">', '<input form="outside" name="extra">']
)
def test_unsupported_controls_do_not_produce_evidence(suffix):
    result = inspect_isolated(HTML.replace("</form>", suffix + "</form>"), URL, 0)
    assert result["contract_evidence"] is None and not result["eligible_for_approval"]


def test_duplicate_hidden_rejected_not_repaired():
    result = inspect_isolated(
        HTML.replace(
            "</fieldset>", '<input type="hidden" name="fixture-nonce" value="PRIVATE"></fieldset>'
        ),
        URL,
        0,
    )
    assert result["status"] == "PARSE_FAILED" and not result["execution_allowed"]
