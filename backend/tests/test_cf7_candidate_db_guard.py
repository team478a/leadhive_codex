"""P1 PostgreSQL guards only; no CF7 preparation API or outbound execution."""

import copy
import importlib.util
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import (
    ApprovalRequest,
    ApprovedEmailReservation,
    ApprovedFormDispatch,
    FormDelivery,
    FormProfile,
    OutreachDraft,
)
from app.services import approved_form
from app.services import human_approval as approval
from app.services.cf7_candidate_contract import digest, snapshot
from tests.test_approval_foundation import create
from tests.test_approval_foundation import workspace as workspace
from tests.test_cf7_candidate_contract import candidate


@pytest.fixture
def candidate_values(db, workspace, users):
    project, company = workspace
    draft = OutreachDraft(company_id=company.id, channel="form", body="fixture")
    profile = FormProfile(company_id=company.id, form_url="https://managed.example/contact/")
    db.add_all([draft, profile])
    db.flush()
    contract = candidate().model_copy(
        update={
            "project_id": project.id,
            "company_id": company.id,
            "source_draft_id": draft.id,
            "form_profile_id": profile.id,
        }
    )
    inner = snapshot(contract)
    outer = {
        "delivery_method": "cf7_candidate_only",
        "project_id": str(project.id),
        "company_id": str(company.id),
        "source_draft_id": str(draft.id),
        "payload_version": 1,
        "cf7_candidate_snapshot": inner,
        "cf7_candidate_snapshot_hash": digest(inner),
    }
    # Internal synthetic DB fixture, not a public creation or approval service.
    return dict(
        id=uuid4(),
        project_id=project.id,
        company_id=company.id,
        channel="form",
        delivery_method="cf7_candidate_only",
        source_draft_id=draft.id,
        form_url=contract.form_url,
        subject=contract.subject,
        body=contract.body,
        sender={v.name: v.value for v in contract.sender},
        field_values={v.name: v.value for v in contract.field_values},
        payload_snapshot=outer,
        payload_hash=approval.payload_hash(outer),
        payload_version=1,
        canonicalization_version="json-v1",
        proposal_id=uuid4(),
        created_by_principal_type="HUMAN",
        created_by_user_id=users[0].id,
        created_at=approval.now(),
        expires_at=approval.now() + timedelta(hours=23),
        status="PENDING",
    )


def insert(db, values):
    db.execute(ApprovalRequest.__table__.insert().values(**values))
    db.flush()
    return db.get(ApprovalRequest, values["id"])


def denied(db, operation, constraint=None):
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        operation()
    if constraint:
        assert error.value.orig.diag.constraint_name == constraint


def test_candidate_is_storable_but_never_consumable(db, candidate_values):
    row = insert(db, candidate_values)
    assert row.status == "PENDING"
    denied(
        db,
        lambda: insert(db, candidate_values | {"id": uuid4(), "status": "CONSUMED"}),
        "ck_cf7_candidate_not_consumed",
    )
    denied(
        db,
        lambda: db.execute(
            text("UPDATE approval_requests SET status='CONSUMED' WHERE id=:id"),
            {"id": row.id},
        ),
    )
    db.refresh(row)
    assert row.status == "PENDING"


@pytest.mark.parametrize(
    "path,value",
    [
        (("delivery_method",), "form_direct"),
        (("project_id",), str(uuid4())),
        (("company_id",), None),
        (("source_draft_id",), str(uuid4())),
        (("payload_version",), "1"),
        (("cf7_candidate_snapshot",), None),
        (("cf7_candidate_snapshot_hash",), None),
        (("cf7_candidate_snapshot", "contract_hash"), "short"),
        (("cf7_candidate_snapshot", "wire_sha256"), None),
        (("cf7_candidate_snapshot", "wire_size"), "123"),
        (("cf7_candidate_snapshot", "wire_size"), 0),
        (("cf7_candidate_snapshot", "wire_size"), 65537),
        (("cf7_candidate_snapshot", "content_type"), None),
        (("cf7_candidate_snapshot", "contract"), None),
        (("cf7_candidate_snapshot", "contract", "environment"), "CONTROLLED_LAB"),
        (("cf7_candidate_snapshot", "contract", "delivery_method"), "form_adapter"),
        (("cf7_candidate_snapshot", "contract", "payload_version"), True),
        (("cf7_candidate_snapshot", "contract", "form_profile_id"), str(uuid4())),
        (("cf7_candidate_snapshot", "contract", "form_url"), "https://other.example/"),
        (("cf7_candidate_snapshot", "contract", "body"), "changed"),
        (("cf7_candidate_snapshot", "contract", "sender"), {}),
        (("cf7_candidate_snapshot", "contract", "field_values"), None),
    ],
)
def test_missing_null_forged_or_mismatched_binding_rejected(db, candidate_values, path, value):
    values = copy.deepcopy(candidate_values)
    node = values["payload_snapshot"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    denied(db, lambda: insert(db, values), "ck_cf7_candidate_binding")


@pytest.mark.parametrize("key", ["cf7_candidate_snapshot", "cf7_candidate_snapshot_hash"])
def test_missing_keys_rejected(db, candidate_values, key):
    del candidate_values["payload_snapshot"][key]
    denied(db, lambda: insert(db, candidate_values), "ck_cf7_candidate_binding")


@pytest.mark.parametrize("method", ["email", "form_direct", "form_adapter"])
def test_candidate_cannot_be_disguised_as_legacy_method(db, candidate_values, method):
    candidate_values["delivery_method"] = method
    denied(db, lambda: insert(db, candidate_values), "ck_cf7_candidate_binding")


def test_source_project_and_draft_ownership_enforced(db, candidate_values, workspace):
    other = OutreachDraft(company_id=workspace[1].id, channel="email", body="other")
    db.add(other)
    db.flush()
    candidate_values["source_draft_id"] = other.id
    candidate_values["payload_snapshot"]["source_draft_id"] = str(other.id)
    candidate_values["payload_snapshot"]["cf7_candidate_snapshot"]["contract"][
        "source_draft_id"
    ] = str(other.id)
    denied(db, lambda: insert(db, candidate_values), "ck_cf7_candidate_binding")


def test_coordinated_project_relabel_cannot_cross_company_boundary(db, candidate_values):
    other = uuid4()
    candidate_values["project_id"] = other
    candidate_values["payload_snapshot"]["project_id"] = str(other)
    candidate_values["payload_snapshot"]["cf7_candidate_snapshot"]["contract"]["project_id"] = str(
        other
    )
    denied(db, lambda: insert(db, candidate_values), "ck_cf7_candidate_binding")


def test_even_approved_candidate_cannot_consume_or_change_payload(db, candidate_values, users):
    # Privileged SQL fixture, not Human approval or a public API path.
    candidate_values.update(
        status="APPROVED",
        approved_by_user_id=users[0].id,
        approved_at=approval.now(),
        approved_payload_hash=candidate_values["payload_hash"],
        approved_payload_version=1,
    )
    row = insert(db, candidate_values)
    for changes in ({"status": "CONSUMED"}, {"subject": "changed"}, {"payload_version": 2}):
        denied(
            db,
            lambda: db.execute(
                ApprovalRequest.__table__.update()
                .where(ApprovalRequest.id == row.id)
                .values(**changes)
            ),
        )
    db.refresh(row)
    assert row.status == "APPROVED" and row.payload_version == 1


@pytest.mark.parametrize("model", [ApprovedFormDispatch, ApprovedEmailReservation])
@pytest.mark.parametrize("marker", [False, True])
def test_execution_links_and_copied_markers_are_rejected(
    db, candidate_values, model, marker, auth, workspace
):
    row = insert(db, candidate_values)
    if marker:
        legacy = create(auth, workspace)
        approval_id = legacy["id"]
        payload = {"cf7_candidate_snapshot": None, "delivery_method": "form_direct"}
    else:
        approval_id = row.id
        payload = {"delivery_method": "form_direct"}  # Stripped candidate marker.
    if model is ApprovedFormDispatch:
        values = dict(
            id=uuid4(),
            approval_id=approval_id,
            project_id=row.project_id,
            company_id=row.company_id,
            draft_id=row.source_draft_id,
            created_by_user_id=row.created_by_user_id,
            idempotency_key=uuid4(),
            request_hash="a" * 64,
            payload_hash=row.payload_hash,
            payload_snapshot=payload,
            form_url=row.form_url,
            reason="",
            status="queued",
        )
    else:
        values = dict(
            id=uuid4(),
            approval_id=approval_id,
            batch_id=uuid4(),
            delivery_id=uuid4(),
            envelope=payload,
            envelope_hash="a" * 64,
            sender_email="sender@example.com",
            recipient_email="recipient@example.com",
        )
    denied(
        db,
        lambda: db.execute(model.__table__.insert().values(**values)),
        "ck_cf7_candidate_no_execution",
    )


@pytest.mark.parametrize("method", ["direct", "adapter", "codex_assisted"])
@pytest.mark.parametrize("encoding", ["canonical", "upper", "hex"])
def test_form_delivery_authorization_cannot_reference_candidate(
    db, candidate_values, method, encoding
):
    row = insert(db, candidate_values)
    identifier = {"canonical": str(row.id), "upper": str(row.id).upper(), "hex": row.id.hex}[
        encoding
    ]
    denied(
        db,
        lambda: db.execute(
            FormDelivery.__table__.insert().values(
                id=uuid4(),
                draft_id=row.source_draft_id,
                company_id=row.company_id,
                form_url=row.form_url,
                delivery_method=method,
                status="pending",
                execution_authorization={"approval_id": identifier},
            )
        ),
        "ck_cf7_candidate_no_execution",
    )


def test_update_existing_delivery_cannot_attach_candidate(db, candidate_values):
    row = insert(db, candidate_values)
    delivery = FormDelivery(
        draft_id=row.source_draft_id,
        company_id=row.company_id,
        form_url=row.form_url,
        delivery_method="direct",
        status="pending",
    )
    db.add(delivery)
    db.flush()
    denied(
        db,
        lambda: db.execute(
            FormDelivery.__table__.update()
            .where(FormDelivery.id == delivery.id)
            .values(execution_authorization={"approval_id": str(row.id)})
        ),
        "ck_cf7_candidate_no_execution",
    )


def migration_module():
    path = Path(__file__).resolve().parents[1] / (
        "migrations/versions/ff51ac0e6437_cf7_candidate_non_execution.py"
    )
    spec = importlib.util.spec_from_file_location("cf7_guard_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_refuses_candidate_evidence(db, candidate_values):
    insert(db, candidate_values)
    with pytest.raises(IntegrityError, match="downgrade forbidden"), db.begin_nested():
        with Operations.context(MigrationContext.configure(db.connection())):
            migration_module().downgrade()
    assert db.scalar(text("SELECT to_regprocedure('cf7_candidate_execution_guard()')"))


def test_guard_roundtrip_without_evidence(db):
    # Transaction rollback restores the original head guard after this DDL test.
    with db.begin_nested() as savepoint:
        with Operations.context(MigrationContext.configure(db.connection())):
            migration_module().downgrade()
            assert not db.scalar(text("SELECT to_regprocedure('cf7_candidate_execution_guard()')"))
            migration_module().upgrade()
            assert db.scalar(text("SELECT to_regprocedure('cf7_candidate_execution_guard()')"))
        savepoint.rollback()


def test_upgrade_stops_if_unprotected_candidate_evidence_exists(db, candidate_values):
    with db.begin_nested() as outer:
        with Operations.context(MigrationContext.configure(db.connection())):
            migration_module().downgrade()
        insert(db, candidate_values)
        with pytest.raises(IntegrityError, match="upgrade stopped"), db.begin_nested():
            with Operations.context(MigrationContext.configure(db.connection())):
                migration_module().upgrade()
        assert db.get(ApprovalRequest, candidate_values["id"]).status == "PENDING"
        outer.rollback()


def test_new_guards_have_no_database_name_or_flag_exception(db):
    for name in ("cf7_candidate_approval_guard", "cf7_candidate_execution_guard"):
        definition = db.scalar(
            text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name + "()"}
        )
        assert "current_database" not in definition and "_test" not in definition
    definition = db.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname='ck_cf7_candidate_not_consumed'"
        )
    )
    assert "current_database" not in definition and "_test" not in definition


def test_all_flags_on_still_no_creation_reservation_or_worker_claim(
    db, candidate_values, auth, workspace, monkeypatch
):
    for name in (
        "agent_features_enabled",
        "outbound_enabled",
        "human_approved_email_enabled",
        "human_approved_form_enabled",
        "form_adapter_preparation_enabled",
        "form_adapter_lab_execution_enabled",
        "legacy_form_delivery_enabled",
    ):
        monkeypatch.setattr(settings, name, True)
    row = insert(db, candidate_values)
    assert (
        auth.post(
            f"/api/projects/{workspace[0].id}/approval-requests",
            json={
                "company_id": str(row.company_id),
                "channel": "form",
                "delivery_method": "cf7_candidate_only",
                "form_url": row.form_url,
                "body": row.body,
                "sender": row.sender,
            },
        ).status_code
        == 422
    )
    # Isolate the method allowlist after approval validity. No new approval API is exposed.
    monkeypatch.setattr(approval, "valid_approved_payload", lambda *args: True)
    for allow_adapter in (False, True):
        with pytest.raises(HTTPException) as error:
            approved_form.validate(db, row, allow_adapter=allow_adapter)
        assert error.value.status_code == 409
    assert approved_form.claim(db) is None
    assert approved_form.claim(db, controlled_lab=True) is None
    assert not db.scalar(
        select(ApprovedFormDispatch.id).where(ApprovedFormDispatch.company_id == row.company_id)
    )
