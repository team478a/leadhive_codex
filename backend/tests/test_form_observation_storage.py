"""O3-B synthetic persistence only; no fetching, sending or live database access."""

import copy
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models import (
    ApprovalRequest,
    EmailDelivery,
    FormDelivery,
    FormObservationEvent,
    FormObservationEvidence,
    OperationJob,
    ProjectMember,
)
from tests.test_approval_foundation import workspace as workspace

LAB = Path(__file__).resolve().parents[2] / "scripts" / "cf7_observer_lab"
sys.path.insert(0, str(LAB))
import storage_contract as contract  # noqa: E402
import store  # noqa: E402
from test_observer import HTML  # noqa: E402


@pytest.fixture
def receipt(db, workspace, users, monkeypatch):
    monkeypatch.setenv("CF7_OBSERVER_STORAGE_LAB", "1")
    project, company = workspace
    company.website_url = "https://managed.example/"
    company.contact_url = contract.PAGE
    db.flush()
    now = db.scalar(text("SELECT clock_timestamp()")).astimezone(timezone.utc)
    run_id, worker = uuid4(), uuid4()
    job = OperationJob(
        project_id=project.id,
        operation_type="cf7_observation",
        status="running",
        payload={
            "company_id": str(company.id),
            "run_id": str(run_id),
            "initiated_by_user_id": str(users[0].id),
        },
        worker_id=worker,
        attempt_count=1,
        lease_expires_at=now + timedelta(minutes=5),
        started_at=now - timedelta(seconds=1),
    )
    db.add(job)
    db.flush()
    binding = contract.Binding(
        project_id=project.id,
        company_project_id=project.id,
        job_project_id=project.id,
        company_id=company.id,
        operation_job_id=job.id,
        run_id=run_id,
        lease_worker_id=worker,
        initiated_by_user_id=users[0].id,
        attempt_number=1,
        company_source_hash=store.source_hash(db, company.id),
    )
    envelope = contract.build(
        binding,
        evidence_id=uuid4(),
        body=HTML.encode(),
        robots=b"User-agent: *\nAllow: /\n",
        pinned_ips=("8.8.8.8", "8.8.8.8"),
        media_type="text/html",
        started_at=now - timedelta(seconds=1),
        observed_at=now,
        now=now,
    )
    db.commit()
    return project, company, job, envelope


def staged(db, envelope):
    s, b = envelope.snapshot, envelope.snapshot.binding
    return FormObservationEvidence(
        id=s.evidence_id,
        project_id=b.project_id,
        company_id=b.company_id,
        operation_job_id=b.operation_job_id,
        run_id=b.run_id,
        attempt_number=b.attempt_number,
        lease_worker_id=b.lease_worker_id,
        initiated_by_user_id=b.initiated_by_user_id,
        observed_at=s.observed_at,
        expires_at=s.expires_at,
        snapshot=s.model_dump(mode="json"),
        canonical_snapshot=contract.canonical(s).decode(),
        snapshot_hash=envelope.snapshot_hash,
    )


def test_save_is_atomic_idempotent_and_does_not_create_outreach(db, receipt, users):
    _, _, job, envelope = receipt
    saved = store.save(db, envelope, users[0])
    db.execute(text("SET CONSTRAINTS observation_saved_atomic IMMEDIATE"))
    db.commit()
    assert store.save(db, envelope, users[0]).id == saved.id
    db.commit()
    assert job.status == "completed" and job.success_count == 1
    assert db.scalar(select(func.count()).select_from(FormObservationEvent)) == 1
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert "hidden" not in json.dumps(saved.snapshot)


@pytest.mark.parametrize(
    "change", ["cancel", "lease", "worker", "attempt", "source", "project", "job_type"]
)
def test_save_rechecks_current_database_binding(db, receipt, users, change):
    _, company, job, envelope = receipt
    if change == "cancel":
        job.cancel_requested = True
    elif change == "lease":
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "worker":
        job.worker_id = uuid4()
    elif change == "attempt":
        job.attempt_count = 2
    elif change == "source":
        company.contact_url = "https://managed.example/changed/"
    elif change == "project":
        job.project_id = uuid4()  # Do not flush nonexistent FK; service comparison still rejects.
    elif change == "job_type":
        job.operation_type = "web_analysis"
    if change == "project":
        with db.no_autoflush, pytest.raises((store.StoreBlocked, contract.ContractBlocked)):
            store.save(db, envelope, users[0])
        db.rollback()
    else:
        db.flush()
        with pytest.raises((store.StoreBlocked, contract.ContractBlocked, ValueError)):
            store.save(db, envelope, users[0])
    assert db.scalar(select(func.count()).select_from(FormObservationEvidence)) == 0


def test_feature_disabled_and_viewer_or_other_user_cannot_save(db, receipt, users, monkeypatch):
    project, _, _, envelope = receipt
    monkeypatch.setenv("CF7_OBSERVER_STORAGE_LAB", "0")
    with pytest.raises(store.StoreBlocked):
        store.save(db, envelope, users[0])
    monkeypatch.setenv("CF7_OBSERVER_STORAGE_LAB", "1")
    db.add(ProjectMember(project_id=project.id, user_id=users[1].id, role="viewer"))
    db.flush()
    with pytest.raises(HTTPException):
        store.save(db, envelope, users[1])


@pytest.mark.parametrize(
    "field,value",
    [
        ("eligible_for_approval", True),
        ("execution_allowed", True),
        ("source_kind", "CONTROLLED_FIXTURE"),
        ("sales_permission", "ALLOWED"),
        ("captcha_state", "CAPTCHA_NONE"),
        ("observer_version", None),
        ("decision", "READY"),
        ("snapshot_schema_version", "unknown"),
    ],
)
def test_raw_sql_cannot_forge_authority_or_unknown_states(db, receipt, field, value):
    _, _, _, envelope = receipt
    row = staged(db, envelope)
    row.snapshot = copy.deepcopy(row.snapshot)
    row.snapshot[field] = value
    row.canonical_snapshot = json.dumps(
        row.snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    row.snapshot_hash = contract.digest(row.canonical_snapshot.encode())
    with pytest.raises(DBAPIError), db.begin_nested():
        db.add(row)
        db.flush()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE form_observation_evidence SET snapshot_hash=snapshot_hash",
        "DELETE FROM form_observation_evidence",
        "TRUNCATE form_observation_evidence CASCADE",
        "UPDATE form_observation_events SET reason_code=reason_code",
        "DELETE FROM form_observation_events",
        "TRUNCATE form_observation_events",
    ],
)
def test_append_only_including_direct_sql(db, receipt, users, statement):
    store.save(db, receipt[3], users[0])
    db.commit()
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text(statement))


def test_missing_ledger_or_completion_cannot_commit(db, receipt):
    with pytest.raises(DBAPIError), db.begin_nested():
        db.add(staged(db, receipt[3]))
        db.flush()
        db.execute(text("SET CONSTRAINTS observation_saved_atomic IMMEDIATE"))


def test_save_rollback_leaves_no_partial_evidence_or_ledger(db, receipt, users):
    with pytest.raises(RuntimeError), db.begin_nested():
        store.save(db, receipt[3], users[0])
        raise RuntimeError("synthetic persistence failure")
    assert db.scalar(select(func.count()).select_from(FormObservationEvidence)) == 0
    assert db.scalar(select(func.count()).select_from(FormObservationEvent)) == 0
    db.refresh(receipt[2])
    assert receipt[2].status == "running"


def test_retire_is_append_only_and_stops_reuse(db, receipt, users):
    envelope = receipt[3]
    row = store.save(db, envelope, users[0])
    db.commit()
    original = copy.deepcopy(row.snapshot)
    store.retire(db, row.id, users[0], row.snapshot_hash)
    db.commit()
    assert row.snapshot == original
    with pytest.raises(contract.ContractBlocked):
        store.save(db, envelope, users[0])
    assert db.scalar(select(func.count()).select_from(FormObservationEvent)) == 2


def test_conflicting_duplicate_result_stops(db, receipt, users):
    envelope = receipt[3]
    store.save(db, envelope, users[0])
    db.commit()
    data = envelope.snapshot.model_dump()
    data["robots_sha256"] = "b" * 64
    snapshot = contract.Snapshot.model_validate(data)
    changed = contract.Envelope(
        snapshot=snapshot, snapshot_hash=contract.digest(contract.canonical(snapshot))
    )
    with pytest.raises(store.StoreBlocked):
        store.save(db, changed, users[0])


def test_parent_delete_move_and_job_binding_change_refused(db, receipt, users):
    project, company, job, envelope = receipt
    store.save(db, envelope, users[0])
    db.commit()
    for sql, params in [
        ("DELETE FROM companies WHERE id=:id", {"id": company.id}),
        ("DELETE FROM operation_jobs WHERE id=:id", {"id": job.id}),
        ("UPDATE companies SET project_id=:p WHERE id=:id", {"p": uuid4(), "id": company.id}),
        ("UPDATE operation_jobs SET payload='{}'::jsonb WHERE id=:id", {"id": job.id}),
        ("UPDATE operation_jobs SET success_count=0 WHERE id=:id", {"id": job.id}),
    ]:
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(text(sql), params)


def test_worker_does_not_claim_or_automatically_recover_observation(db, receipt):
    from app.worker import claim_job, recover_stale_jobs

    job = receipt[2]
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()
    recover_stale_jobs(db)
    db.refresh(job)
    assert job.status == "running"
    job.status = "queued"
    db.flush()
    assert claim_job(db) is None


def test_migration_downgrade_refuses_existing_evidence(db, receipt, users):
    store.save(db, receipt[3], users[0])
    db.commit()
    spec = importlib.util.spec_from_file_location(
        "observation_migration",
        LAB.parents[1]
        / "backend"
        / "migrations"
        / "versions"
        / "0263cd208659_form_observation_storage.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with (
        pytest.raises(DBAPIError),
        db.begin_nested(),
        Operations.context(MigrationContext.configure(db.connection())),
    ):
        module.downgrade()


@pytest.mark.parametrize("case", ["project", "lease", "cancel", "source", "hash", "value", "null"])
def test_insert_guard_rejects_direct_database_bypass(db, receipt, case):
    _, company, job, envelope = receipt
    row = staged(db, envelope)
    row.snapshot = copy.deepcopy(row.snapshot)
    if case == "project":
        row.snapshot["binding"]["company_project_id"] = str(uuid4())
    elif case == "lease":
        job.worker_id = uuid4()
    elif case == "cancel":
        job.cancel_requested = True
    elif case == "source":
        company.website_url = "https://managed.example/changed/"
    elif case == "value":
        row.snapshot["structure_summary"]["controls"][0]["value"] = "secret"
    elif case == "null":
        row.snapshot["structure_summary"] = None
    row.canonical_snapshot = json.dumps(
        row.snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    row.snapshot_hash = (
        contract.digest(row.canonical_snapshot.encode()) if case != "hash" else "b" * 64
    )
    db.flush()
    with pytest.raises(DBAPIError), db.begin_nested():
        db.add(row)
        db.flush()


def test_database_ledger_forgery_and_duplicate_saved_event_refused(db, receipt, users):
    row = store.save(db, receipt[3], users[0])
    db.commit()
    for principal, actor, digest in [
        ("AGENT", users[0].id, row.snapshot_hash),
        ("HUMAN", users[1].id, row.snapshot_hash),
        ("SYSTEM", users[0].id, "b" * 64),
        ("SYSTEM", users[0].id, row.snapshot_hash),
    ]:
        with pytest.raises(DBAPIError), db.begin_nested():
            db.add(
                FormObservationEvent(
                    project_id=row.project_id,
                    company_id=row.company_id,
                    operation_job_id=row.operation_job_id,
                    evidence_id=row.id,
                    actor_user_id=actor,
                    principal_type=principal,
                    event_type="SAVED",
                    reason_code="EVIDENCE_SAVED",
                    snapshot_hash=digest,
                    created_at=db.scalar(text("SELECT clock_timestamp()")),
                )
            )
            db.flush()


def test_revoked_editor_and_changed_notes_are_distinct(db, receipt, users):
    project, company, _, envelope = receipt
    company.notes = "営業メモの変更"
    db.flush()
    row = store.save(db, envelope, users[0])
    db.commit()
    member = ProjectMember(project_id=project.id, user_id=users[1].id, role="editor")
    db.add(member)
    db.flush()
    member.role = "viewer"
    db.flush()
    with pytest.raises(HTTPException):
        store.retire(db, row.id, users[1], row.snapshot_hash)


def test_existing_api_cannot_retry_observation(db, receipt, auth):
    job = receipt[2]
    job.status = "failed"
    db.flush()
    response = auth.post(f"/api/operations/{job.id}/retry")
    assert response.status_code == 409
