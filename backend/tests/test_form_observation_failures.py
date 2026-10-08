"""Typed failure stage diagnostics and cooperative shutdown, owned TLS only."""

from importlib import import_module
from threading import Event
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import FormObservationEvidence, FormObservationJobEvent, OperationJob
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_observation_runner import driver as driver
from tests.test_form_observation_runner import ready, runner


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("dns", "OBSERVATION_DNS_FAILED"),
        ("unsafe_dns", "OBSERVATION_UNSAFE_DNS"),
        ("robots", "OBSERVATION_ROBOTS_INVALID"),
        ("response", "OBSERVATION_RESPONSE_INVALID"),
        ("parse", "OBSERVATION_PARSE_FAILED"),
        ("contract", "OBSERVATION_CONTRACT_INVALID"),
    ],
)
def test_failure_is_classified_without_storing_error_or_body(
    db, driver, workspace, users, failure, expected
):
    case, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    if failure in {"dns", "unsafe_dns"}:
        kwargs = (
            {"side_effect": runner.fetch.transport.TransportBlocked("untrusted-secret")}
            if failure == "dns"
            else {"return_value": ("127.0.0.1",)}
        )
        context = patch.object(runner.fetch.transport, "resolve", **kwargs)
    elif failure == "parse":
        context = patch.object(
            runner.fetch.observer, "analyze", side_effect=ValueError("untrusted-secret")
        )
    elif failure == "contract":
        context = patch.object(runner.contract, "build", side_effect=ValueError("untrusted-secret"))
    else:
        from contextlib import nullcontext

        context = nullcontext()
        if failure == "robots":
            case.routes["/robots.txt"] = (
                200,
                [("Content-Type", "text/plain")],
                b"User-agent: *\nCrawl-delay: 1\n",
            )
        else:
            case.routes["/contact/"] = (
                200,
                [("Content-Type", "application/json")],
                b"untrusted-secret",
            )
    with context:
        assert runner.run(sessions, binding, context=case.lab.context) is None
    db.expire_all()
    assert db.get(OperationJob, job_id).error_message == expected
    events = db.scalars(
        select(FormObservationJobEvent)
        .where(FormObservationJobEvent.operation_job_id == job_id)
        .order_by(FormObservationJobEvent.created_at, FormObservationJobEvent.id)
    ).all()
    assert events[-1].event_type == "FAILED" and events[-1].reason_code == expected
    assert "untrusted-secret" not in str([row.reason_code for row in events])
    assert db.scalar(select(func.count()).select_from(FormObservationEvidence)) == 0


def test_downgrade_refuses_to_rewrite_new_diagnostic_history(db, driver, workspace, users):
    _, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    stop = Event()
    stop.set()
    assert runner.run(sessions, binding, stop=stop) is None
    revision = import_module("migrations.versions.0485ef420871_observation_failure_codes")
    with pytest.raises(IntegrityError), db.begin_nested():
        with Operations.context(MigrationContext.configure(db.connection())):
            revision.downgrade()
    db.expire_all()
    assert db.get(OperationJob, job_id).error_message == "RUNNER_STOPPED"
    assert (
        db.scalar(
            select(func.count())
            .select_from(FormObservationJobEvent)
            .where(FormObservationJobEvent.reason_code == "RUNNER_STOPPED")
        )
        == 1
    )


@pytest.mark.parametrize("after_robots", [False, True])
def test_runner_stop_is_system_cancelled_and_never_stores_evidence(
    db, driver, workspace, users, after_robots
):
    case, sessions = driver
    job_id, binding = ready(driver, workspace, users)
    stop = Event()
    original = runner.fetch.get

    def get(*args, **kwargs):
        result = original(*args, **kwargs)
        stop.set()
        return result

    if not after_robots:
        stop.set()
    with patch.object(runner.fetch, "get", side_effect=get):
        assert runner.run(sessions, binding, context=case.lab.context, stop=stop) is None
    db.expire_all()
    job = db.get(OperationJob, job_id)
    assert job.status == "cancelled" and job.error_message == "RUNNER_STOPPED"
    assert len(case.lab.events) == int(after_robots)
    event = db.scalar(
        select(FormObservationJobEvent).where(FormObservationJobEvent.event_type == "CANCELLED")
    )
    assert event.principal_type == "SYSTEM" and event.actor_user_id is None
    assert db.scalar(select(func.count()).select_from(FormObservationEvidence)) == 0
