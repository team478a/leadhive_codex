"""Real commits, independent connections and process death in fresh disposable databases."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApprovalRequest, ApprovedFormDispatch, FormDelivery
from app.services import approved_form, controlled_form_execution
from tests.controlled_adapter_transport import LabTransport
from tests.fixture_plan_http import FixtureServer
from tests.test_approval_foundation import approve, challenge
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_adapter_preparation import adapter_source as adapter_source
from tests.test_form_adapter_preparation import prepare, reserve
from tests.test_form_approval_preparation import form_source as form_source


@pytest.fixture
def db(monkeypatch):
    # Only a database created by this fixture can be dropped. No existing DB is modified.
    from app import database

    source = make_url(os.environ["TEST_DATABASE_URL"])
    assert source.database.endswith("_test")
    name = "leadhive_lab_" + uuid4().hex + "_test"
    assert name.startswith("leadhive_lab_") and name.endswith("_test")
    admin = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = source.set(database=name)
    lab_engine = create_engine(url)
    monkeypatch.setattr(database, "engine", lab_engine)
    monkeypatch.setattr(settings, "database_url", url.render_as_string(hide_password=False))
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
        with Session(lab_engine) as session:
            yield session
    finally:
        lab_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.parametrize("before_post", [True, False])
def test_real_process_loss_preserves_unknown_without_retry(
    auth, adapter_source, db, monkeypatch, tmp_path, before_post
):
    monkeypatch.setenv("FORM_ADAPTER_LAB", "1")
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    monkeypatch.setattr(settings, "form_adapter_lab_execution_enabled", True)
    item = prepare(auth, adapter_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    response = reserve(auth, item)
    assert response.status_code == 201
    row_id = UUID(response.json()["id"])
    marker = tmp_path / "committed.txt"
    with FixtureServer("hold_accepted") as lab:
        args = [
            sys.executable,
            "-m",
            "tests.controlled_adapter_process",
            str(row_id),
            str(lab.port),
        ]
        if before_post:
            args.append(str(marker))
        env = os.environ.copy() | {
            "FORM_ADAPTER_PREPARATION_ENABLED": "true",
            "FORM_ADAPTER_LAB_EXECUTION_ENABLED": "true",
            "HUMAN_APPROVED_FORM_ENABLED": "true",
            "OUTBOUND_ENABLED": "true",
        }
        process = subprocess.Popen(
            args,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 20
            while (
                not (marker.exists() if before_post else lab.accepted.is_set())
                and time.monotonic() < deadline
            ):
                assert process.poll() is None, "Lab process exited before controlled attempt"
                time.sleep(0.05)
            assert marker.exists() if before_post else lab.accepted.is_set()
            process.kill()
            process.wait(timeout=10)
            # Separate connection proves actual commit; not a nested test savepoint.
            with Session(db.get_bind()) as independent:
                row = independent.get(ApprovedFormDispatch, row_id)
                assert row.status == "unknown" and row.started_at and row.delivery_id
                assert independent.get(FormDelivery, row.delivery_id).status == "unknown"
                assert independent.get(ApprovalRequest, item["id"]).status == "CONSUMED"
                assert approved_form.claim(independent, controlled_lab=True) is None
                controlled_form_execution.run(independent, row, LabTransport(lab.port))
                assert reserve(auth, item).status_code == 409
                assert len(lab.posts) == (0 if before_post else 1)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)  # Never print child environment/credentials.


def test_parallel_workers_post_only_once(auth, adapter_source, db, monkeypatch):
    monkeypatch.setenv("FORM_ADAPTER_LAB", "1")
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    monkeypatch.setattr(settings, "form_adapter_lab_execution_enabled", True)
    item = prepare(auth, adapter_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    response = reserve(auth, item)
    assert response.status_code == 201
    with FixtureServer() as lab:
        env = os.environ.copy() | {
            "FORM_ADAPTER_PREPARATION_ENABLED": "true",
            "FORM_ADAPTER_LAB_EXECUTION_ENABLED": "true",
            "HUMAN_APPROVED_FORM_ENABLED": "true",
            "OUTBOUND_ENABLED": "true",
        }
        args = [
            sys.executable,
            "-m",
            "tests.controlled_adapter_process",
            response.json()["id"],
            str(lab.port),
        ]
        processes = [
            subprocess.Popen(
                args,
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        try:
            for process in processes:
                process.communicate(timeout=20)
                assert process.returncode == 0
            assert len(lab.posts) == 1
            db.expire_all()
            assert db.get(ApprovedFormDispatch, response.json()["id"]).status == "submitted"
            assert approved_form.claim(db, controlled_lab=True) is None
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)
