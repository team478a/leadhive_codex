import json
import subprocess

import pytest

from app.services import cf7_static_inspection as service
from app.services.cf7_static_parser import inspect_html

URL = "https://fixture.example/contact/"
HTML = """<link rel="https://api.w.org/" href="https://fixture.example/wp-json/">
<form class="wpcf7-form" method="post">
<input name="_wpcf7" value="7" type="hidden">
<input name="_wpcf7_version" value="6.1.4" type="hidden">
<input name="_wpcf7_locale" value="ja" type="hidden">
<input name="_wpcf7_unit_tag" value="private-token" type="hidden">
<input name="your-name" value="PRIVATE PERSON">
<textarea name="your-message">PRIVATE BODY</textarea></form>"""


def test_isolated_parser_has_no_authority_or_sensitive_output():
    result = service.inspect_isolated(HTML, URL, 0)
    assert result["status"] == "CF7_CANDIDATE"
    assert result["version"] == "6.1.4"
    assert result["form_id_valid"] and result["markers_complete"]
    assert result["rest_link_same_origin"]
    assert result["method_is_post"]
    assert not result["execution_allowed"] and not result["eligible_for_approval"]
    output = json.dumps(result)
    for secret in ("PRIVATE", "private-token", "your-name", URL):
        assert secret not in output


@pytest.mark.parametrize(
    "replacement,key,value",
    [
        (("6.1.4", "sk-proj-PRIVATE"), "version", None),
        (
            ("https://fixture.example/wp-json/", "https://other.example/wp-json/"),
            "rest_link_same_origin",
            False,
        ),
        (("https://fixture.example/wp-json/", "http://127.0.0.1/"), "rest_link_same_origin", False),
        (("</form>", '<input type="file" name="file"></form>'), "file_inputs", 1),
        (("</form>", "<input required></form>"), "missing_names", 1),
        (("</form>", '<input type="date" name="date"></form>'), "unsupported_controls", 1),
        (("post", "get"), "method_is_post", False),
        (("</form>", '</form><base href="https://other.example/">'), "base_override", True),
    ],
)
def test_static_facts_do_not_assert_execution(replacement, key, value):
    result = inspect_html(HTML.replace(*replacement), URL, 0)
    assert result[key] == value
    assert not result["execution_allowed"]


@pytest.mark.parametrize(
    "html,index,status",
    [
        ("<form></form>", 0, "NOT_CF7"),
        (HTML, 1, "FORM_MISSING"),
        (HTML.replace("<form class=", "<form><form class="), 0, "PARSE_FAILED"),
        (HTML.replace('name="your-name"', 'name="your-name" name="other"'), 0, "PARSE_FAILED"),
        ("x" * 262145, 0, "LIMIT_EXCEEDED"),
    ],
    ids=["not-cf7", "missing-form", "nested", "duplicate-attribute", "large-html"],
)
def test_bounded_failures(html, index, status):
    assert service.inspect_isolated(html, URL, index)["status"] == status


def test_timeout_uses_fixed_reason_and_does_not_inherit_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "PRIVATE")

    def timeout(command, **kwargs):
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "-I" in command and kwargs["timeout"] == 5
        assert "shell" not in kwargs
        raise subprocess.TimeoutExpired(command, 5, output=b"PRIVATE")

    monkeypatch.setattr(service.subprocess, "run", timeout)
    result = service.inspect_isolated(HTML, URL, 0)
    assert result == {
        "status": "PARSE_FAILED",
        "execution_allowed": False,
        "eligible_for_approval": False,
    }


def test_saved_results_reject_arbitrary_strings_and_authority():
    result = service.inspect_isolated(HTML, URL, 0)
    assert service.validate_saved(result | {"execution_allowed": True}) is None
    assert service.validate_saved(result | {"version": "PRIVATE"}) is None
    assert service.validate_saved(result | {"html": "PRIVATE"}) is None
    assert service.validate_saved({"status": "PARSE_FAILED", "secret": "PRIVATE"}) == {
        "status": "PARSE_FAILED",
        "execution_allowed": False,
        "eligible_for_approval": False,
    }


def test_duplicate_hidden_markers_and_visible_markers_are_not_verified():
    duplicate = HTML.replace("</form>", '<input name="_wpcf7" value="8" type="hidden"></form>')
    assert service.inspect_isolated(duplicate, URL, 0)["status"] == "PARSE_FAILED"
    visible = HTML.replace('type="hidden"', 'type="text"')
    result = service.inspect_isolated(visible, URL, 0)
    assert not result["markers_complete"] and not result["form_id_valid"]
    assert result["version"] is None


def test_rest_link_must_be_a_root_and_scripts_remain_inert():
    html = (
        HTML.replace("/wp-json/", "/contact/")
        + "<script>throw Error('PRIVATE'); fetch('https://other.example')</script>"
    )
    result = service.inspect_isolated(html, URL, 0)
    assert result["status"] == "CF7_CANDIDATE" and not result["rest_link_same_origin"]
    assert "PRIVATE" not in json.dumps(result)


CONTRACT_HTML = HTML.replace("private-token", "wpcf7-f7-o1").replace(
    "</form>",
    '<input type="hidden" name="_wpcf7_container_post" value="0">'
    '<input type="hidden" name="_wpcf7_posted_data_hash" value=""></form>',
)


def test_contract_hidden_shape_is_separate_from_basic_markers():
    basic = service.inspect_isolated(HTML, URL, 0)
    assert basic["markers_complete"]
    assert not basic["contract_shape"]["hidden_complete"]
    full = service.inspect_isolated(CONTRACT_HTML, URL, 0)
    assert full["contract_shape"]["hidden_shape_valid"]
    assert not full["eligible_for_approval"] and not full["execution_allowed"]


@pytest.mark.parametrize(
    "old,new",
    [
        ("6.1.4", "6.2"),
        ("wpcf7-f7-o1", "wpcf7-f8-o1"),
        ('value="7"', 'value="2147483648"'),
        ('value="ja"', 'value="PRIVATE"'),
        (
            'name="_wpcf7_posted_data_hash" value=""',
            'name="_wpcf7_posted_data_hash" value="PRIVATE"',
        ),
    ],
    ids=["unreviewed-version", "unit-mismatch", "id-overflow", "locale", "posted-hash"],
)
def test_contract_hidden_mismatch_never_claims_compatibility(old, new):
    result = service.inspect_isolated(CONTRACT_HTML.replace(old, new), URL, 0)
    assert not result["contract_shape"]["hidden_shape_valid"]
    assert "PRIVATE" not in json.dumps(result)


def test_selection_groups_extra_hidden_and_defaults_are_explicit():
    html = CONTRACT_HTML.replace(
        "</form>",
        '<input type="hidden" name="nonce" value="PRIVATE">'
        '<input type="radio" name="group[]"><input type="radio" name="group[]">'
        '<select name="choice"></select>'
        '<input type="checkbox" name="consent" checked disabled></form>',
    )
    result = service.inspect_isolated(html, URL, 0)
    shape = result["contract_shape"]
    assert result["unsupported_controls"] == 3
    assert shape["radio_controls"] == 2 and shape["select_controls"] == 1
    assert shape["invalid_names"] == 2 and shape["repeated_names"] == 1
    assert shape["extra_hidden"] == 1 and shape["disabled_controls"] == 1
    assert shape["checkbox_controls"] == shape["checked_checkboxes"] == 1
    assert "PRIVATE" not in json.dumps(result) and "nonce" not in json.dumps(result)


def test_older_saved_diagnosis_is_unknown_not_success():
    result = service.inspect_isolated(HTML, URL, 0)
    result.pop("contract_shape")
    assert service.validate_saved(result)["contract_shape"] is None
    malicious = service.inspect_isolated(HTML, URL, 0)
    malicious["contract_shape"]["extra_hidden"] = "PRIVATE"
    assert service.validate_saved(malicious) is None
