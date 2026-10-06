"""Real owned TLS fixture + transaction-isolated PostgreSQL; never external sites."""

import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
import job_runner as runner  # noqa: E402
import test_fetch as tls_fixture  # noqa: E402


@pytest.fixture
def driver(db, workspace, users, monkeypatch):
    case = tls_fixture.FetchTests("test_gets_robots_then_contact_without_authority_or_credentials")
    case.setUp()
    monkeypatch.setenv("CF7_OBSERVER_JOB_LAB", "1")
    monkeypatch.setenv("CF7_OBSERVER_STORAGE_LAB", "1")
    workspace[1].website_url = "https://managed.example/"
    workspace[1].contact_url = runner.fetch.PAGE
    db.commit()

    def sessions():
        return Session(bind=db.get_bind(), join_transaction_mode="create_savepoint")

    try:
        yield case, sessions
    finally:
        case.doCleanups()


def ready(driver, workspace, users, actor=None):
    _, sessions = driver
    job_id = runner.enqueue(sessions, workspace[1].id, (actor or users[0]).id)
    binding = runner.claim(sessions, job_id, uuid4())
    assert binding
    return job_id, binding


def evidence_count(db):
    return db.scalar(select(func.count()).select_from(FormObservationEvidence))


def test_owned_tls_get_stores_only_diagnostic_and_completes_atomically(
    db, driver, workspace, users
):
    case, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    assert runner.claim(sessions, job_id, uuid4()) is None
    result = runner.run(sessions, binding, context=case.lab.context)
    assert result
    db.expire_all()
    row = db.get(FormObservationEvidence, result)
    assert row.snapshot["body_sha256"] == runner.contract.digest(case.routes["/contact/"][2])
    assert row.snapshot["robots_sha256"] == runner.contract.digest(case.routes["/robots.txt"][2])
    assert row.snapshot["fetch_summary"]["body_bytes"] == len(case.routes["/contact/"][2])
    assert not row.snapshot["execution_allowed"] and not row.snapshot["eligible_for_approval"]
    assert db.get(OperationJob, job_id).status == "completed"
    assert db.scalar(select(func.count()).select_from(FormObservationEvent)) == 1
    assert [event[:2] for event in case.lab.events] == [
        ("GET", "/robots.txt"),
        ("GET", "/contact/"),
    ]
    assert runner.run(sessions, binding, context=case.lab.context) is None
    assert len(case.lab.events) == 2 and evidence_count(db) == 1
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "flag", ["CF7_OBSERVER_JOB_LAB", "CF7_OBSERVER_GET_LAB", "CF7_OBSERVER_STORAGE_LAB"]
)
def test_default_off_boundary_stops_before_dns(db, driver, workspace, users, monkeypatch, flag):
    case, sessions = driver
    monkeypatch.delenv(flag)
    with pytest.raises((runner.JobStopped, runner.store.StoreBlocked)):
        runner.enqueue(sessions, workspace[1].id, users[0].id)
    case.dns.assert_not_called()
    assert evidence_count(db) == 0


def test_project_and_source_boundaries_and_active_uniqueness(db, driver, workspace, users):
    case, sessions = driver
    with pytest.raises(HTTPException):
        runner.enqueue(sessions, workspace[1].id, users[1].id)
    db.add(ProjectMember(project_id=workspace[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    with pytest.raises(HTTPException):
        runner.enqueue(sessions, workspace[1].id, users[1].id)
    job_id = runner.enqueue(sessions, workspace[1].id, users[0].id)
    with pytest.raises(IntegrityError):
        runner.enqueue(sessions, workspace[1].id, users[0].id)
    workspace[1].contact_url = "https://external.example/contact/"
    db.commit()
    assert runner.claim(sessions, job_id, uuid4()) is None
    db.expire_all()
    assert db.get(OperationJob, job_id).status == "failed"
    case.dns.assert_not_called()


@pytest.mark.parametrize(
    "change", ["cancel", "url", "role", "lease", "worker", "flag", "run", "type", "payload"]
)
def test_changes_after_robots_prevent_page_get_and_saving(
    db, driver, workspace, users, monkeypatch, change
):
    case, sessions = driver
    member = ProjectMember(project_id=workspace[0].id, user_id=users[1].id, role="editor")
    db.add(member)
    db.commit()
    job_id, binding = ready(driver, workspace, users, actor=users[1])
    original = runner.fetch.get

    def get(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs["robots"]:
            with sessions() as session:
                job = session.get(OperationJob, job_id)
                if change == "cancel":
                    job.cancel_requested = True
                elif change == "url":
                    session.get(
                        type(workspace[1]), workspace[1].id
                    ).website_url = "https://managed.example/changed/"
                elif change == "role":
                    session.get(ProjectMember, member.id).role = "viewer"
                elif change == "lease":
                    job.lease_expires_at = session.scalar(
                        text("SELECT clock_timestamp()")
                    ) - timedelta(seconds=1)
                elif change == "worker":
                    job.worker_id = uuid4()
                elif change == "run":
                    job.payload = job.payload | {"run_id": str(uuid4())}
                elif change == "type":
                    job.operation_type = "web_analysis"
                elif change == "payload":
                    job.payload = None
                else:
                    monkeypatch.delenv("CF7_OBSERVER_JOB_LAB")
                session.commit()
        return result

    monkeypatch.setattr(runner.fetch, "get", get)
    assert runner.run(sessions, binding, context=case.lab.context) is None
    db.expire_all()
    assert evidence_count(db) == 0
    assert [event[1] for event in case.lab.events] == ["/robots.txt"]
    expected = (
        "running"
        if change in {"worker", "run", "type", "payload"}
        else "cancelled"
        if change == "cancel"
        else "failed"
    )
    assert db.get(OperationJob, job_id).status == expected


@pytest.mark.parametrize("case_name", ["robots", "http", "tls"])
def test_fetch_failures_do_not_persist_or_retry(db, driver, workspace, users, case_name):
    case, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    if case_name == "robots":
        case.routes["/robots.txt"] = (
            200,
            [("Content-Type", "text/plain")],
            b"User-agent: *\nDisallow: /\n",
        )
    elif case_name == "http":
        case.routes["/contact/"] = (503, [("Content-Type", "text/html")], b"secret failure")
    context = None if case_name == "tls" else case.lab.context
    assert runner.run(sessions, binding, context=context) is None
    db.expire_all()
    job = db.get(OperationJob, job_id)
    expected = {
        "robots": "OBSERVATION_ROBOTS_DENIED",
        "http": "OBSERVATION_HTTP_REJECTED",
        "tls": "OBSERVATION_TLS_FAILED",
    }[case_name]
    assert job.status == "failed" and job.error_message == expected
    assert evidence_count(db) == 0
    requests = len(case.lab.events)
    assert runner.claim(sessions, job_id, uuid4()) is None
    assert len(case.lab.events) == requests


def test_crash_recovery_does_not_fetch_and_fences_the_late_worker(db, driver, workspace, users):
    case, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    job = db.get(OperationJob, job_id)
    job.lease_expires_at = db.scalar(text("SELECT clock_timestamp()")) - timedelta(seconds=1)
    db.commit()
    assert runner.recover(sessions) == 1
    assert runner.recover(sessions) == 0
    assert runner.run(sessions, binding, context=case.lab.context) is None
    db.expire_all()
    assert db.get(OperationJob, job_id).error_message == "WORKER_LOST"
    assert evidence_count(db) == 0 and case.lab.events == []


def test_cancelled_queue_never_claims(db, driver, workspace, users):
    case, sessions = driver
    job_id = runner.enqueue(sessions, workspace[1].id, users[0].id)
    job = db.get(OperationJob, job_id)
    job.cancel_requested = True
    db.commit()
    assert runner.claim(sessions, job_id, uuid4()) is None
    db.expire_all()
    assert db.get(OperationJob, job_id).status == "cancelled" and case.lab.events == []


def test_staged_save_failure_rolls_back_evidence_ledger_and_completion(
    db, driver, workspace, users, monkeypatch
):
    case, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    original = runner.store.save

    def fail_after_staging(*args, **kwargs):
        original(*args, **kwargs)
        raise runner.store.StoreBlocked("secret synthetic exception")

    monkeypatch.setattr(runner.store, "save", fail_after_staging)
    assert runner.run(sessions, binding, context=case.lab.context) is None
    db.expire_all()
    assert evidence_count(db) == 0
    assert db.scalar(select(func.count()).select_from(FormObservationEvent)) == 0
    job = db.get(OperationJob, job_id)
    assert job.status == "failed" and job.error_message == "OBSERVATION_STORAGE_FAILED"
    assert job.success_count == 0 and job.failed_count == 1
    assert len(case.lab.events) == 2


def test_source_change_after_full_fetch_discards_receipt(db, driver, workspace, users, monkeypatch):
    case, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    original = runner.fetch.observe_owned_page

    def changed(**kwargs):
        receipt = original(**kwargs)
        assert "<" not in repr(receipt) and "fixture-token" not in repr(receipt)
        with sessions() as session:
            session.get(
                type(workspace[1]), workspace[1].id
            ).website_url = "https://managed.example/changed/"
            session.commit()
        return receipt

    monkeypatch.setattr(runner.fetch, "observe_owned_page", changed)
    assert runner.run(sessions, binding, context=case.lab.context) is None
    db.expire_all()
    assert evidence_count(db) == 0 and db.get(OperationJob, job_id).status == "failed"
    assert len(case.lab.events) == 2
