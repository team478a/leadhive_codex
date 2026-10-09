"""Offline multipart confirmation evidence; no live site or actual submission."""

import json
import socket
from datetime import datetime, timedelta, timezone
from html import escape
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.config import settings
from app.services.form_adapter_contract import ExecutableFormPlan
from app.services.form_execution_plan import (
    ExecutionPlan,
    FixtureResult,
    InputValue,
    PlanStep,
    classify_fixture_result,
    plan_hash,
)
from app.services.form_intelligence.compatibility import assess_delivery_compatibility
from tests.multipart_confirmation_fixture import review_confirmation


@pytest.fixture(autouse=True)
def offline_only(monkeypatch, legacy_delivery_test_mode):
    def denied(*args, **kwargs):
        raise AssertionError("No network in multipart confirmation fixture")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)


def plan():
    return ExecutionPlan(
        adapter_id="fixture_js_confirmation",
        adapter_version="1",
        project_id=UUID(int=1),
        company_id=UUID(int=2),
        form_id="anonymous-multipart-confirmation",
        form_url="https://fixture.example/contact",
        field_fingerprint="a" * 64,
        route_fingerprint="b" * 64,
        payload_version=1,
        sender=(InputValue(name="email", value="fixture@example.com"),),
        subject="Unapproved fixture subject",
        body="Unapproved 日本語\r\nfixture draft",
        field_values=(
            InputValue(name="email", value="fixture@example.com"),
            InputValue(name="message", value="Unapproved 日本語\r\nfixture draft"),
        ),
        steps=(
            PlanStep(kind="confirm_post", url="https://fixture.example/confirm", method="POST"),
            PlanStep(kind="submit", url="https://fixture.example/submit", method="POST"),
        ),
    )


def confirmation():
    hidden = "".join(
        f'<input type="hidden" name="{escape(value.name)}" value="{escape(value.value)}">'
        for value in plan().field_values
    )
    return (
        '<form method="post" enctype="multipart/form-data" '
        'action="https://fixture.example/submit">'
        + hidden
        + '<input type="hidden" name="fixture_token" value="PRIVATE-FIXTURE-TOKEN">'
        + '<input type="submit" name="submitFinal" value="send"></form>'
    )


DEFAULT_HTML = object()


def review(html=DEFAULT_HTML, **changes):
    now = datetime.now(timezone.utc)
    parameters = dict(
        snapshot=plan(),
        current=plan(),
        html=confirmation() if html is DEFAULT_HTML else html,
        response_url="https://fixture.example/confirm",
        expected_hash=plan_hash(plan()),
        expected_version=1,
        expected_token="PRIVATE-FIXTURE-TOKEN",
        token_payload_hash=plan_hash(plan()),
        expires_at=now + timedelta(minutes=5),
        now=now,
        observation_id=UUID(int=3),
        already_reviewed=frozenset(),
    )
    parameters.update(changes)
    result = review_confirmation(**parameters)
    assert not result["execution_allowed"] and not result["eligible_for_approval"]
    assert not result["automatic_retry_allowed"] and not result["submitted"]
    assert "PRIVATE-FIXTURE-TOKEN" not in json.dumps(result)
    assert "fixture@example.com" not in json.dumps(result)
    return result


def test_valid_confirmation_remains_review_not_authorization_or_submission():
    assert review()["status"] == "REVIEW_REQUIRED"
    assert not settings.outbound_enabled and not settings.legacy_form_delivery_enabled
    form = BeautifulSoup(confirmation(), "html.parser").form
    assert form is not None and not form.select('input[type="file"]')
    assert not assess_delivery_compatibility(form, plan().form_url).supported
    with pytest.raises(ValidationError):
        ExecutableFormPlan.model_validate_json(plan().model_dump_json())


@pytest.mark.parametrize(
    "changes",
    [
        {"project_id": UUID(int=9)},
        {"company_id": UUID(int=9)},
        {"form_id": "other"},
        {"field_fingerprint": "c" * 64},
        {"route_fingerprint": "c" * 64},
        {"body": "Changed"},
        {"subject": "Changed"},
        {"sender": (InputValue(name="email", value="other@example.com"),)},
        {"field_values": (InputValue(name="message", value="Changed"),)},
        {"payload_version": 2},
    ],
)
def test_payload_and_identity_mutation_invalidates_review(changes):
    assert review(current=plan().model_copy(update=changes))["reason"] == "PAYLOAD_BINDING_CHANGED"


@pytest.mark.parametrize(
    "html,reason",
    [
        (
            confirmation().replace("Unapproved 日本語", "Changed 日本語"),
            "CONFIRMATION_VALUES_CHANGED",
        ),
        (confirmation().replace("PRIVATE-FIXTURE-TOKEN", "OTHER-TOKEN"), "TOKEN_CHANGED"),
        (
            confirmation().replace(
                "https://fixture.example/submit", "https://other.example/submit"
            ),
            "CONFIRMATION_ROUTE_CHANGED",
        ),
        (confirmation().replace('method="post"', 'method="get"'), "CONFIRMATION_ROUTE_CHANGED"),
        (
            confirmation().replace('name="submitFinal"', 'name="submitConfirm"'),
            "UNEXPECTED_SUBMIT_CONTROL",
        ),
        (confirmation().replace('type="submit"', 'type="hidden"'), "FINAL_SUBMIT_NOT_EXPLICIT"),
        (
            confirmation().replace("</form>", '<input type="file" name="upload"></form>'),
            "UNSUPPORTED_CONFIRMATION_CONTROL",
        ),
        (
            confirmation().replace(
                "</form>", '<input type="hidden" name="message" value="Changed"></form>'
            ),
            "DUPLICATE_CONFIRMATION_CONTROL",
        ),
        (
            confirmation().replace(
                "</form>", '<input type="hidden" name="extra" value="Unknown"></form>'
            ),
            "CONFIRMATION_VALUES_CHANGED",
        ),
        (
            confirmation().replace('name="submitFinal"', 'name="submitFinal" formaction="/other"'),
            "CONFIRMATION_CONTROL_OVERRIDE",
        ),
        (confirmation() + "<form></form>", "AMBIGUOUS_CONFIRMATION_FORM"),
        (confirmation() + "<script>untrusted()</script>", "CONFIRMATION_ROUTE_CHANGED"),
        (confirmation() + " " * 65536, "CONFIRMATION_TOO_LARGE"),
    ],
    ids=[
        "changed-body",
        "changed-token",
        "external-action",
        "get-method",
        "confirmation-button-not-final",
        "hidden-not-submit",
        "upload",
        "duplicate-name",
        "unknown-field",
        "submit-override",
        "multiple-forms",
        "script",
        "oversized",
    ],
)
def test_confirmation_changes_are_blocked(html, reason):
    result = review(html)
    assert result["status"] == "BLOCKED" and result["reason"] == reason


def test_token_expiry_binding_and_replay_require_new_review():
    assert (
        review(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))["reason"]
        == "TOKEN_EXPIRED_OR_UNBOUND_TIME"
    )
    assert review(token_payload_hash="0" * 64)["reason"] == "TOKEN_PAYLOAD_BINDING_CHANGED"
    assert review(already_reviewed=frozenset({UUID(int=3)}))["reason"] == "OBSERVATION_REPLAY"


def test_lost_response_is_unknown_never_automatically_retried():
    result = review(html=None)
    assert result["status"] == "UNKNOWN"


def test_confirmation_success_message_is_not_final_acceptance():
    evidence = FixtureResult(
        form_id=plan().form_id,
        attempt_id=UUID(int=3),
        stage="confirmation",
        status="fixture_accepted",
    )
    assert (
        classify_fixture_result(evidence, form_id=plan().form_id, attempt_id=UUID(int=3))
        == "UNKNOWN"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://fixture.example/contact",
        "https://fixture.example/submit",
        "https://other.example/confirm",
    ],
)
def test_response_must_be_bound_to_confirmation_stage(url):
    assert review(response_url=url)["reason"] == "RESPONSE_NOT_CONFIRMATION_STAGE"


@pytest.mark.parametrize(
    "changes", [{"expected_hash": "0" * 64}, {"expected_version": 2}, {"expected_version": True}]
)
def test_expected_binding_cannot_be_changed(changes):
    assert review(**changes)["reason"] == "PAYLOAD_BINDING_CHANGED"


def test_json_roundtrip_preserves_snapshot_without_granting_authority():
    loaded = ExecutionPlan.model_validate_json(plan().model_dump_json())
    assert plan_hash(loaded) == plan_hash(plan())
    assert review(snapshot=loaded, current=loaded)["status"] == "REVIEW_REQUIRED"
