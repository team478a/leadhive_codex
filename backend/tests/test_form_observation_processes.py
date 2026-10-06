"""Independent OS processes and committed connections in an owned disposable DB."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models import Company, FormObservationJobEvent, OperationJob, Project, TargetProfile, User
from app.services import form_observation_jobs as service

BACKEND = Path(__file__).resolve().parents[1]


def test_two_process_claims_and_dead_worker_recovery(monkeypatch):
    original = make_url(os.environ["TEST_DATABASE_URL"])
    name = "leadhive_observation_process_" + uuid4().hex[:24] + "_test"
    admin = create_engine(original.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = original.set(database=name)
    env = os.environ | {
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "TEST_DATABASE_URL": url.render_as_string(hide_password=False),
    }
    env.update({flag: "1" for flag in service.FLAGS})
    processes = []
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text('CREATE DATABASE "' + name + '"'))
        created = True
        # A fresh process is required because migrations import app.database.engine.
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            timeout=90,
        )
        assert result.returncode == 0, "Isolated migration failed (details intentionally redacted)"
        engine = create_engine(url)
        with Session(engine) as db:
            user = User(email="process@example.com", password_hash="not-a-login-secret")
            db.add(user)
            db.flush()
            profile = TargetProfile(user_id=user.id, profile_name="Process test")
            db.add(profile)
            db.flush()
            project = Project(
                user_id=user.id,
                project_name="Process test",
                target_profile_id=profile.id,
                sales_objective="No external execution",
                region="全国",
            )
            db.add(project)
            db.flush()
            company = Company(
                project_id=project.id,
                company_name="Synthetic only",
                source="url",
                website_url=service.WEBSITE,
                contact_url=service.CONTACT,
                domain="managed.example",
            )
            db.add(company)
            db.commit()
            # This internal test seeds only the queued state and audit transaction.
            for flag in service.FLAGS:
                monkeypatch.setenv(flag, "1")
            job = service.enqueue(db, company, user)
            db.commit()
            job_id, user_id = job.id, user.id
        for _ in range(2):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(BACKEND / "tests" / "observation_claim_process.py"),
                        str(job_id),
                    ],
                    cwd=BACKEND,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        # Both processes receive the same committed job and start together.
        for process in processes:
            assert process.stdout.readline().strip() == "READY"
        for process in processes:
            process.stdin.write("CLAIM\n")
            process.stdin.flush()
        outcomes = []
        for process in processes:
            output, _ = process.communicate(timeout=30)
            assert process.returncode == 0, "Claim subprocess failed (details redacted)"
            outcomes.append(output.strip())
        assert sorted(outcomes) == ["CLAIMED", "NOT_CLAIMED"]
        with Session(engine) as db:
            job = db.get(OperationJob, job_id)
            assert job.status == "running" and job.attempt_count == 1
            assert len(db.scalars(select(FormObservationJobEvent)).all()) == 2
            # The winning process exited without fetch/finish. No automatic retry.
            job.lease_expires_at = db.scalar(text("SELECT clock_timestamp()")) - timedelta(
                seconds=1
            )
            db.commit()
            service.recover(db, job, db.get(User, user_id))
            db.commit()
            assert job.status == "failed" and job.error_message == "WORKER_LOST"
            assert [
                row.event_type
                for row in db.scalars(
                    select(FormObservationJobEvent).order_by(FormObservationJobEvent.created_at)
                ).all()
            ] == ["QUEUED", "CLAIMED", "RECOVERED"]
            for table in (
                "form_observation_evidence",
                "approval_requests",
                "email_deliveries",
                "form_deliveries",
            ):
                assert db.scalar(text("SELECT count(*) FROM " + table)) == 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        if engine:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                # Only the exact UUID-named database created above; no shared DB termination.
                connection.execute(text('DROP DATABASE "' + name + '"'))
        admin.dispose()
