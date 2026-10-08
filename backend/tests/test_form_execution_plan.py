from uuid import UUID

import pytest
from pydantic import ValidationError

from app.services.form_execution_plan import (
    ExecutionPlan,
    FixtureResult,
    InputValue,
    PlanError,
    PlanStep,
    classify_fixture_result,
    plan_hash,
    validate_plan,
)

PROJECT = UUID(int=1)
COMPANY = UUID(int=2)
ATTEMPT = UUID(int=3)
SUBMIT = PlanStep(kind="submit", url="https://fixture.example/submit", method="POST")
LOCAL = PlanStep(kind="confirm_local", url="https://fixture.example/contact", method="NONE")
CONFIRM = PlanStep(kind="confirm_post", url="https://fixture.example/confirm", method="POST")


def plan(**changes):
    values = dict(
        adapter_id="fixture_cf7",
        adapter_version="1",
        project_id=PROJECT,
        company_id=COMPANY,
        form_id="anonymous-form",
        form_url="https://fixture.example/contact",
        field_fingerprint="a" * 64,
        route_fingerprint="b" * 64,
        payload_version=1,
        sender=(InputValue(name="email", value="sender@example.com"),),
        subject="匿名提案",
        body="承認対象の本文",
        field_values=(
            InputValue(name="message", value="承認対象の本文"),
            InputValue(name="privacy", value="yes"),
        ),
        steps=(SUBMIT,),
    )
    return ExecutionPlan(**(values | changes))


@pytest.mark.parametrize("steps", [(LOCAL, SUBMIT), (CONFIRM, SUBMIT)])
def test_known_js_fixture_plans(steps):
    item = plan(adapter_id="fixture_js_confirmation", steps=steps)
    validate_plan(item, item, expected_hash=plan_hash(item), expected_version=1)


def test_cf7_fixture_and_order_independent_named_inputs():
    item = plan()
    current = plan(field_values=tuple(reversed(item.field_values)))
    validate_plan(item, current, expected_hash=plan_hash(item), expected_version=1)
    assert len(plan_hash(item)) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"project_id": UUID(int=9)},
        {"company_id": UUID(int=9)},
        {"form_id": "different"},
        {"field_fingerprint": "c" * 64},
        {"route_fingerprint": "c" * 64},
        {"subject": "変更"},
        {"body": "変更"},
        {"sender": (InputValue(name="email", value="changed@example.com"),)},
        {"field_values": (InputValue(name="message", value="変更"),)},
        {
            "field_values": (
                InputValue(name="message", value="承認対象の本文 "),
                InputValue(name="privacy", value="yes"),
            )
        },
        {
            "field_values": (
                InputValue(name="message", value="承認対象の本文"),
                InputValue(name="privacy", value="no"),
            )
        },
        {"adapter_id": "fixture_js_confirmation", "steps": (LOCAL, SUBMIT)},
    ],
)
def test_payload_route_and_boundary_changes_require_new_preparation(change):
    item = plan()
    with pytest.raises(PlanError):
        validate_plan(item, plan(**change), expected_hash=plan_hash(item), expected_version=1)


@pytest.mark.parametrize("snapshot_version,current_version,expected", [(1, 2, 1), (1, 1, 2)])
def test_version_conflicts(snapshot_version, current_version, expected):
    item = plan(payload_version=snapshot_version)
    with pytest.raises(PlanError, match="version"):
        validate_plan(
            item,
            plan(payload_version=current_version),
            expected_hash=plan_hash(item),
            expected_version=expected,
        )


def test_tampered_hash():
    item = plan()
    with pytest.raises(PlanError, match="integrity"):
        validate_plan(item, item, expected_hash="0" * 64, expected_version=1)


@pytest.mark.parametrize("version", [True, "1", 0])
def test_expected_version_is_strict(version):
    item = plan()
    with pytest.raises(PlanError):
        validate_plan(item, item, expected_hash=plan_hash(item), expected_version=version)


def test_bypass_copy_cannot_create_valid_hash():
    item = plan().model_copy(update={"steps": ()})
    with pytest.raises(ValidationError):
        plan_hash(item)


@pytest.mark.parametrize(
    "change",
    [
        {"adapter_id": "real_cf7"},
        {"adapter_version": "2"},
        {"confirmed": True},
        {"contract_version": 2},
        {"payload_version": 0},
        {"field_fingerprint": "bad"},
        {"sender": ()},
        {"field_values": ()},
        {"field_values": (InputValue(name="same", value="a"), InputValue(name="same", value="b"))},
        {"steps": ()},
        {"steps": (SUBMIT, SUBMIT)},
        {"steps": (CONFIRM, SUBMIT)},
    ],
)
def test_unknown_or_malformed_contract_rejected(change):
    with pytest.raises(ValidationError):
        plan(**change)


@pytest.mark.parametrize(
    "url",
    [
        "https://other.example/submit",
        "http://fixture.example/submit",
        "https://fixture.example:444/submit",
        "https://fixture.example@evil.example/submit",
        "https://127.0.0.1/submit",
        "https://169.254.169.254/submit",
        "https://fixture.example/submit?target=other",
        "https://fixture.example/submit#changed",
    ],
)
def test_destination_change_rejected(url):
    with pytest.raises(ValidationError):
        plan(steps=(PlanStep(kind="submit", url=url, method="POST"),))


@pytest.mark.parametrize(
    "steps", [(SUBMIT, LOCAL), (LOCAL, SUBMIT, SUBMIT), (CONFIRM,), (LOCAL, CONFIRM, SUBMIT)]
)
def test_js_unknown_sequence_rejected(steps):
    with pytest.raises(ValidationError):
        plan(adapter_id="fixture_js_confirmation", steps=steps)


def test_nested_contract_is_immutable_and_rejects_script():
    item = plan()
    with pytest.raises(ValidationError):
        item.field_values[0].value = "変更"
    with pytest.raises(ValidationError):
        PlanStep(kind="submit", url=SUBMIT.url, method="POST", script="arbitrary()")


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "SUBMITTED"),
        ({"stage": "confirmation"}, "UNKNOWN"),
        ({"status": "validation_error"}, "UNKNOWN"),
        ({"status": "200"}, "UNKNOWN"),
        ({"status": "mail_sent"}, "UNKNOWN"),
        ({"status": "timeout"}, "UNKNOWN"),
        ({"form_id": "different"}, "UNKNOWN"),
        ({"attempt_id": UUID(int=9)}, "UNKNOWN"),
    ],
)
def test_only_exact_final_synthetic_evidence_counts(changes, expected):
    evidence = FixtureResult(
        **(
            dict(
                form_id="anonymous-form",
                attempt_id=ATTEMPT,
                stage="final",
                status="fixture_accepted",
            )
            | changes
        )
    )
    assert (
        classify_fixture_result(evidence, form_id="anonymous-form", attempt_id=ATTEMPT) == expected
    )
