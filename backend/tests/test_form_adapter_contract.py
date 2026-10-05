from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.model_approval import ApprovalRequest
from app.models import ApprovedFormDispatch, EmailDelivery, FormDelivery
from app.services.form_adapter_contract import (
    ExecutableFormPlan,
    adapter_plan_hash,
    adapter_snapshot,
    digest,
    validate_adapter_snapshot,
)
from app.services.form_execution_plan import InputValue, PlanError, PlanStep
from tests.test_approval_foundation import approve, challenge, create, expected
from tests.test_approval_foundation import workspace as workspace


def plan(**changes):
    return ExecutableFormPlan(
        **(
            dict(
                environment="CONTROLLED_LAB",
                adapter_id="controlled_lab_single_post",
                adapter_version="1",
                project_id=UUID(int=1),
                company_id=UUID(int=2),
                source_draft_id=UUID(int=3),
                form_profile_id=UUID(int=4),
                form_id="anonymous",
                form_url="https://fixture.example/contact",
                field_fingerprint="a" * 64,
                route_fingerprint="b" * 64,
                payload_version=1,
                sender=tuple(
                    InputValue(name=k, value=v)
                    for k, v in dict(
                        name="Human", email="sender@example.com", company="", phone=""
                    ).items()
                ),
                subject="Synthetic subject",
                body="Synthetic body",
                field_values=(InputValue(name="message", value="Synthetic body"),),
                steps=(
                    PlanStep(kind="submit", url="https://fixture.example/submit", method="POST"),
                ),
            )
            | changes
        )
    )


def validate(snapshot, current, **changes):
    return validate_adapter_snapshot(
        snapshot,
        current,
        **(
            dict(
                expected_hash=digest(snapshot),
                expected_version=1,
                project_id=UUID(int=1),
                company_id=UUID(int=2),
                source_draft_id=UUID(int=3),
            )
            | changes
        ),
    )


def test_separate_contract_canonical_roundtrip():
    item = plan()
    snapshot = adapter_snapshot(item)
    loaded = ExecutableFormPlan.model_validate_json(item.model_dump_json())
    reordered = plan(sender=tuple(reversed(item.sender)))
    validate(snapshot, loaded)
    validate(snapshot, reordered)
    assert adapter_plan_hash(item) == adapter_plan_hash(reordered)
    assert snapshot["adapter_plan_hash"] == adapter_plan_hash(item)
    with pytest.raises(ValidationError):
        from app.services.form_execution_plan import ExecutionPlan

        ExecutionPlan.model_validate_json(item.model_dump_json())


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "PRODUCTION"},
        {"adapter_id": "fixture_cf7"},
        {"adapter_id": "real_cf7"},
        {"adapter_version": "2"},
        {"contract_version": 2},
        {"canonicalization_version": "unknown"},
        {"channel": "email"},
        {"delivery_method": "form_direct"},
        {"form_url": "http://127.0.0.1/contact"},
        {"form_url": "https://real.example/contact"},
        {"form_url": "https://fixture.example/contact?x=1"},
        {"payload_version": True},
        {"payload_version": 0},
        {"sender": ()},
        {"field_values": ()},
        {"script": "fetch('https://real.example')"},
        {"steps": ()},
        {
            "steps": (
                PlanStep(
                    kind="confirm_local", url="https://fixture.example/contact", method="NONE"
                ),
            )
        },
        {"steps": (PlanStep(kind="submit", url="https://real.example/submit", method="POST"),)},
    ],
)
def test_unknown_registry_and_arbitrary_operations_rejected(changes):
    with pytest.raises(ValidationError):
        plan(**changes)
    if "script" not in changes:
        with pytest.raises(ValidationError):
            adapter_snapshot(plan().model_copy(update=changes))


@pytest.mark.parametrize(
    "key,value",
    [
        ("project_id", UUID(int=9)),
        ("company_id", UUID(int=9)),
        ("source_draft_id", UUID(int=9)),
        ("form_profile_id", UUID(int=9)),
        ("form_id", "different"),
        ("field_fingerprint", "c" * 64),
        ("route_fingerprint", "c" * 64),
        ("payload_version", 2),
        ("subject", "different"),
        ("body", "different"),
        ("field_values", (InputValue(name="message", value="different"),)),
        (
            "sender",
            tuple(
                InputValue(name=k, value=v)
                for k, v in dict(
                    name="Other", email="sender@example.com", company="", phone=""
                ).items()
            ),
        ),
    ],
)
def test_changed_current_plan_requires_new_approval(key, value):
    with pytest.raises(PlanError):
        validate(adapter_snapshot(plan()), plan(**{key: value}))


@pytest.mark.parametrize(
    "key,value",
    [
        ("adapter_plan_hash", "0" * 64),
        ("body", "changed"),
        ("form_action_url", "https://real.example/submit"),
        ("delivery_method", "form_direct"),
        ("payload_version", 2),
        ("attachment_metadata", [{"name": "unexpected"}]),
        ("extra", "unexpected"),
    ],
)
def test_outer_binding_rejected_even_after_outer_rehash(key, value):
    with pytest.raises(PlanError):
        validate(adapter_snapshot(plan()) | {key: value}, plan())


@pytest.mark.parametrize(
    "changes",
    [
        {"project_id": UUID(int=9)},
        {"company_id": UUID(int=9)},
        {"source_draft_id": UUID(int=9)},
        {"expected_hash": "0" * 64},
        {"expected_version": 2},
        {"expected_version": True},
    ],
)
def test_server_boundary_and_version_checks(changes):
    with pytest.raises(PlanError):
        validate(adapter_snapshot(plan()), plan(), **changes)


def test_adapter_not_exposed_and_sql_consumption_forbidden(auth, workspace, db):
    item = create(auth, workspace)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    row = db.get(ApprovalRequest, item["id"])
    copied = {c.name: getattr(row, c.name) for c in ApprovalRequest.__table__.columns}
    copied.update(
        id=uuid4(), proposal_id=uuid4(), delivery_method="form_adapter", status="CONSUMED"
    )
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.execute(ApprovalRequest.__table__.insert().values(**copied))
    assert error.value.orig.diag.constraint_name == "ck_adapter_contract_not_consumed"

    # Reject even forged legacy approval evidence: the new mode has no API path.
    from tests.test_approval_foundation import proposal

    body = proposal(workspace[1]) | {"delivery_method": "form_adapter"}
    assert (
        auth.post(f"/api/projects/{workspace[0].id}/approval-requests", json=body).status_code
        == 422
    )
    assert (
        auth.post(
            f"/api/approval-requests/{item['id']}/form-dispatch",
            json=expected(item) | {"idempotency_key": str(uuid4())},
        ).status_code
        == 409
    )
    for model in (ApprovedFormDispatch, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_unknown_fields_duplicates_and_sender_validation():
    item = plan()
    invalid = [
        {"field_values": item.field_values * 2},
        {
            "field_values": (
                InputValue(name="a", value="x" * 20000),
                InputValue(name="b", value="x" * 20000),
            )
        },
    ]
    for email, name in [("invalid", "Human"), ("sender@example.com", " ")]:
        invalid.append(
            {
                "sender": tuple(
                    InputValue(name=k, value=v)
                    for k, v in dict(name=name, email=email, company="", phone="").items()
                )
            }
        )
    for changes in invalid:
        with pytest.raises(ValidationError):
            plan(**changes)


def test_downgrade_refuses_adapter_records_without_removing_guard(auth, workspace, db):
    import importlib.util
    from pathlib import Path

    item = create(auth, workspace)
    row = db.get(ApprovalRequest, item["id"])
    copied = {c.name: getattr(row, c.name) for c in ApprovalRequest.__table__.columns}
    copied.update(id=uuid4(), proposal_id=uuid4(), delivery_method="form_adapter")
    db.execute(ApprovalRequest.__table__.insert().values(**copied))
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/fc2e7b9d3104_adapter_contract_guard.py"
    )
    spec = importlib.util.spec_from_file_location("adapter_guard_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    context = MigrationContext.configure(db.connection())
    with pytest.raises(IntegrityError, match="downgrade forbidden"), db.begin_nested():
        with Operations.context(context):
            migration.downgrade()
