import json
import subprocess

import pytest

from app.services import cf7_large_page_review as service
from app.services.cf7_static_inspection import inspect_isolated, validate_saved
from tests.test_cf7_static_inspection import CONTRACT_HTML, URL


def large(suffix=""):
    return CONTRACT_HTML + '<script>var unused="' + "x" * 270000 + '";</script>' + suffix


def test_large_page_diagnostic_does_not_replace_regular_inspection():
    markup = large()
    assert inspect_isolated(markup, URL, 0)["status"] == "LIMIT_EXCEEDED"
    result = service.review_saved_large_page(markup, URL, 0)
    assert result["status"] == "REVIEW_ONLY" and result["whole_page_scanned"]
    assert result["cf7_marker"] and result["version"] == "6.1.4"
    assert result["permission_status"] == "UNKNOWN" and result["human_review_required"]
    assert not result["execution_allowed"] and not result["eligible_for_approval"]
    assert "contract_evidence" not in result and "contract_shape" not in result
    assert validate_saved(result) is None


@pytest.mark.parametrize(
    "suffix,key",
    [
        ('<script src="https://other.example/recaptcha.js"></script>', "captcha_marker_detected"),
        ('<script>var secret="hcaptcha";</script>', "captcha_marker_detected"),
        ('<base href="https://other.example/">', "base_override"),
        ('<input form="outside" name="separate">', "external_control"),
    ],
)
def test_page_tail_is_scanned_not_only_selected_form(suffix, key):
    result = service.review_saved_large_page(large(suffix), URL, 0)
    assert result["status"] == "REVIEW_ONLY" and result[key]
    assert not result["execution_allowed"]


def test_no_script_execution_values_or_raw_names_in_output():
    markup = large(
        '<script>fetch("https://other.example/PRIVATE");throw Error("PRIVATE");</script>'
    )
    markup = markup.replace(
        "</form>", '<input type="hidden" name="secret-token" value="PRIVATE"></form>'
    )
    result = service.review_saved_large_page(markup, URL, 0)
    assert result["status"] == "REVIEW_ONLY" and result["extra_hidden"] == 1
    output = json.dumps(result)
    for secret in ("PRIVATE", "secret-token", "your-name", "your-message", URL):
        assert secret not in output


@pytest.mark.parametrize("index", [True, -1, 20, "0"])
def test_invalid_index_rejected(index):
    assert service.review_saved_large_page(large(), URL, index)["status"] == "PARSE_FAILED"


def test_size_tag_control_and_malformed_limits_preserved():
    assert service.review_saved_large_page("界" * 349526, URL, 0)["status"] == "LIMIT_EXCEEDED"
    assert (
        service.review_saved_large_page("<span></span>" * 10001, URL, 0)["status"] == "PARSE_FAILED"
    )
    assert (
        service.review_saved_large_page(
            CONTRACT_HTML.replace("<form class=", "<form><form class="), URL, 0
        )["status"]
        == "PARSE_FAILED"
    )
    many = CONTRACT_HTML.replace("</form>", '<input name="extra">' * 101 + "</form>")
    assert service.review_saved_large_page(many, URL, 0)["status"] == "PARSE_FAILED"


def test_duplicate_attribute_anywhere_in_page_remains_ambiguous():
    markup = large('<div class="one" class="two">ambiguous</div>')
    result = service.review_saved_large_page(markup, URL, 0)
    assert result["status"] == "PARSE_FAILED"
    assert result["human_review_required"] and not result["execution_allowed"]


def test_timeout_is_isolated_and_failure_has_no_secrets(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "PRIVATE")

    def timeout(command, **kwargs):
        assert command[-1] == "--large-review-only" and "-I" in command
        assert kwargs["timeout"] == 5 and "SMTP_PASSWORD" not in kwargs["env"]
        raise subprocess.TimeoutExpired(command, 5, output=b"PRIVATE")

    monkeypatch.setattr(service.subprocess, "run", timeout)
    result = service.review_saved_large_page(large(), URL, 0)
    assert result["status"] == "PARSE_FAILED" and "PRIVATE" not in json.dumps(result)


def test_subprocess_output_cannot_grant_authority(monkeypatch):
    result = service.review_saved_large_page(large(), URL, 0)
    result["execution_allowed"] = True
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(result).encode()),
    )
    assert service.review_saved_large_page(large(), URL, 0)["status"] == "PARSE_FAILED"
