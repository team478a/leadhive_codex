from types import SimpleNamespace
from uuid import uuid4

from app.services.form_missing_diagnostics import (
    classify_missing_form,
    missing_form_candidates_query,
)


def log(event_type, **details):
    return SimpleNamespace(event_type=event_type, details=details)


def profile(version="2.2"):
    return SimpleNamespace(analysis_version=version, last_analyzed_at=None)


def test_reason_classifier_prefers_embedded_evidence_and_keeps_secondary_reasons():
    logs = [
        log("analysis_started"),
        log(
            "contact_page_found",
            url="https://example.com/contact",
            discovery_method="LINK",
        ),
        log("analysis_completed", finding="DOM_CONTACT_FORM_NOT_FOUND"),
        log("analysis_completed", finding="EMBEDDED_FORM_UNVERIFIED"),
    ]
    result = classify_missing_form(profile(), logs, "https://example.com")
    assert result["primary_reason"] == "EMBED_UNVERIFIED"
    assert result["secondary_reasons"] == ["PAGE_FOUND_NO_FORM"]
    assert result["last_reached_url"] == "https://example.com/contact"


def test_reason_classifier_uses_only_logs_after_latest_start():
    logs = [
        log("analysis_started"),
        log("analysis_completed", finding="EMBEDDED_FORM_UNVERIFIED"),
        log("analysis_started"),
        log(
            "contact_page_found",
            url="https://example.com/contact",
            discovery_method="GUESSED_PATH",
        ),
    ]
    result = classify_missing_form(profile(), logs, "https://example.com")
    assert result["primary_reason"] == "GUESSED_PATH_ONLY"
    assert result["secondary_reasons"] == []


def test_guess_only_failures_are_not_misclassified_as_root_fetch_failures():
    logs = [
        log("analysis_started"),
        log(
            "analysis_failed",
            finding="FETCH_FAILED",
            discovery_method="GUESSED_PATH",
            url="https://example.com/contact.html",
        ),
    ]
    result = classify_missing_form(profile(), logs, "https://example.com")
    assert result["primary_reason"] == "GUESSED_PATH_ONLY"
    assert "ROOT_FETCH_FAILED" not in result["secondary_reasons"]


def test_legacy_version_is_retained_as_secondary_reason():
    result = classify_missing_form(profile("2.1"), [log("analysis_started")], "https://example.com")
    assert result["primary_reason"] == "NO_CONTACT_PAGE"
    assert result["secondary_reasons"] == ["UNKNOWN_LEGACY"]


def test_reanalysis_and_diagnostic_queries_share_latest_eligible_profile_scope():
    query = missing_form_candidates_query(uuid4())
    sql = str(query).lower()
    assert "row_number() over" in sql
    assert "form_found" in sql
    assert "do_not_contact" in sql
    assert "analysis_status" in sql
    assert "sales_contact_status" in sql
