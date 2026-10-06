"""Human API queue -> independent CLI -> owned TLS -> read, stop and crash recovery."""

import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import get_db
from app.form_observation_job_routes import router as job_router
from app.form_observation_routes import router as read_router
from app.models import (
    Company,
    FormObservationEvidence,
    FormObservationJobEvent,
    OperationJob,
    Project,
    TargetProfile,
    User,
)
from app.routes import router as auth_router
from app.security import password_hasher
from app.services.approval_principals import reject_mixed_credentials
from app.services.form_observation_jobs import FLAGS
from tests.conftest import PASSWORD
from tests.test_form_observation_runner import runner

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "cf7_observer_lab" / "owned_runner.py"


@pytest.fixture(scope="module")
def owned_database():
    original = make_url(os.environ["TEST_DATABASE_URL"])
    name = "leadhive_observation_run_" + uuid4().hex[:24] + "_test"
    url = original.set(database=name)
    admin = create_engine(
        original.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    engine = None
    created = False
    env = os.environ | {
        "TEST_DATABASE_URL": url.render_as_string(hide_password=False),
        "DATABASE_URL": url.render_as_string(hide_password=False),
    }
    env.update({flag: "1" for flag in FLAGS})
    try:
        with admin.connect() as connection:
            connection.execute(text('CREATE DATABASE "' + name + '"'))
        created = True
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            capture_output=True,
            timeout=90,
        )
        assert result.returncode == 0, "Owned launcher migration failed; details redacted"
        engine = create_engine(url, hide_parameters=True)
        yield engine, env
    finally:
        if engine:
            with engine.connect() as connection:
                for table in ("approval_requests", "email_deliveries", "form_deliveries"):
                    assert connection.scalar(text("SELECT count(*) FROM " + table)) == 0
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text('DROP DATABASE "' + name + '"'))
        admin.dispose()


@pytest.fixture
def queued(owned_database, monkeypatch):
    engine, env = owned_database
    for flag in FLAGS:
        monkeypatch.setenv(flag, "1")
    app = FastAPI(dependencies=[Depends(reject_mixed_credentials)])
    for router in (auth_router, job_router, read_router):
        app.include_router(router)

    def sessions():
        return Session(engine)

    def request_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = request_db
    with sessions() as db:
        user = User(
            email="launcher-" + uuid4().hex + "@example.com",
            password_hash=password_hasher.hash(PASSWORD),
        )
        db.add(user)
        db.flush()
        profile = TargetProfile(user_id=user.id, profile_name="Synthetic launcher")
        db.add(profile)
        db.flush()
        project = Project(
            user_id=user.id,
            project_name="Synthetic launcher",
            target_profile_id=profile.id,
            sales_objective="No outreach",
            region="全国",
        )
        db.add(project)
        db.flush()
        company = Company(
            project_id=project.id,
            source="url",
            company_name="Owned synthetic only",
            website_url="https://managed.example/",
            contact_url=runner.fetch.PAGE,
            domain="managed.example",
        )
        db.add(company)
        db.commit()
        email, company_id = user.email, company.id
    with TestClient(app) as client:
        assert (
            client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code
            == 200
        )
        response = client.post(f"/api/companies/{company_id}/form-observation-jobs", json={})
        assert response.status_code == 202
        yield sessions, env, client, company_id, response.json()["id"]


def command(job_id, scenario="success"):
    return [sys.executable, str(CLI), "--owned-fixture", "--job-id", job_id, "--scenario", scenario]


@pytest.mark.parametrize(
    "scenario,exit_code,reason",
    [
        ("success", 0, None),
        ("robots-denied", 3, "OBSERVATION_ROBOTS_DENIED"),
        ("http-rejected", 3, "OBSERVATION_HTTP_REJECTED"),
        ("response-invalid", 3, "OBSERVATION_RESPONSE_INVALID"),
        ("tls-failed", 3, "OBSERVATION_TLS_FAILED"),
        ("timeout", 3, "OBSERVATION_TIMEOUT"),
    ],
)
def test_human_queue_to_cli_to_read(queued, scenario, exit_code, reason):
    sessions, env, client, company_id, job_id = queued
    result = subprocess.run(
        command(job_id, scenario), env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == exit_code, "Owned CLI exit mismatch; details redacted"
    assert "JOB_CLAIMED" in result.stdout and result.stderr == ""
    data = client.get(f"/api/companies/{company_id}/form-observation-jobs").json()
    job = data["items"][0]
    assert job["status"] == ("completed" if scenario == "success" else "failed")
    assert job["reason_code"] == reason and not job["execution_allowed"]
    assert job["events"][0]["reason_code"] == (reason or "EVIDENCE_SAVED")
    observations = client.get(f"/api/companies/{company_id}/form-observations").json()["items"]
    assert len(observations) == int(scenario == "success")
    if observations:
        assert (
            not observations[0]["eligible_for_approval"]
            and not observations[0]["execution_allowed"]
        )
    retry = subprocess.run(command(job_id), env=env, capture_output=True, text=True, timeout=15)
    assert retry.returncode == 2 and "JOB_NOT_CLAIMED" in retry.stdout
    with sessions() as db:
        assert db.get(OperationJob, UUID(job["id"])).attempt_count == 1


def test_cli_rejects_missing_confirmation_flag_or_database_scope(queued):
    _, env, _, _, job_id = queued
    for flag in FLAGS:
        result = subprocess.run(
            command(job_id), env=env | {flag: "0"}, capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 2 and "RUNNER_CONFIGURATION_REJECTED" in result.stdout
    unconfirmed = subprocess.run(
        [sys.executable, str(CLI), "--job-id", job_id], env=env, capture_output=True, timeout=15
    )
    assert unconfirmed.returncode == 2
    bad = env | {
        "TEST_DATABASE_URL": "postgresql+psycopg://private:do-not-print@127.0.0.1/production"
    }
    result = subprocess.run(command(job_id), env=bad, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and "do-not-print" not in result.stdout + result.stderr
    override = make_url(env["TEST_DATABASE_URL"]).update_query_dict({"host": "external.example"})
    override_env = env | {
        "TEST_DATABASE_URL": override.render_as_string(hide_password=False),
        "DATABASE_URL": override.render_as_string(hide_password=False),
    }
    result = subprocess.run(
        command(job_id), env=override_env, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 2 and "RUNNER_CONFIGURATION_REJECTED" in result.stdout


@pytest.mark.parametrize("graceful", [False, True])
def test_process_shutdown_and_human_recovery_fences_late_worker(queued, graceful):
    if graceful and os.name == "nt":
        pytest.skip("Windows TerminateProcess is not SIGTERM; Event shutdown is covered separately")
    sessions, env, client, company_id, job_id = queued
    # Force termination can bypass child TemporaryDirectory cleanup; parent owns all temp artifacts.
    with tempfile.TemporaryDirectory(prefix="leadhive-runner-parent-") as temp:
        child_env = env | {"TMPDIR": temp, "TMP": temp, "TEMP": temp}
        process = subprocess.Popen(
            command(job_id, "timeout"),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            assert json.loads(process.stdout.readline())["code"] == "JOB_CLAIMED"
            if graceful:
                process.send_signal(signal.SIGTERM)
            else:
                process.kill()
            output, stderr = process.communicate(timeout=20)
            assert stderr == ""
            with sessions() as db:
                from uuid import UUID

                job = db.get(OperationJob, UUID(job_id))
                if graceful:
                    assert process.returncode == 4 and "RUNNER_STOPPED" in output
                    assert job.status == "cancelled" and job.error_message == "RUNNER_STOPPED"
                else:
                    assert job.status == "running"
                    binding = runner.current(db, job, job.worker_id)
                    job.lease_expires_at = db.scalar(text("SELECT clock_timestamp()")) - timedelta(
                        seconds=1
                    )
                    db.commit()
            if not graceful:
                response = client.post(f"/api/form-observation-jobs/{job_id}/recover", json={})
                assert (
                    response.status_code == 200 and response.json()["reason_code"] == "WORKER_LOST"
                )
                with patch.object(
                    runner.fetch.transport,
                    "resolve",
                    side_effect=AssertionError("Late worker fetched"),
                ):
                    assert runner.run(sessions, binding) is None
            observations = client.get(f"/api/companies/{company_id}/form-observations").json()[
                "items"
            ]
            assert observations == []
            with sessions() as db:
                assert not db.scalar(
                    select(FormObservationEvidence.id).where(
                        FormObservationEvidence.company_id == company_id
                    )
                )
                assert db.scalar(
                    select(FormObservationJobEvent.id).where(
                        FormObservationJobEvent.operation_job_id == job_id,
                        FormObservationJobEvent.event_type.in_(("RECOVERED", "CANCELLED")),
                    )
                )
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
