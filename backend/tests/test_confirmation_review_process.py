"""Independent processes and real commits in disposable PostgreSQL databases."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    EmailDelivery,
    FormDelivery,
    OutreachAuditEvent,
)
from app.services import controlled_confirmation_review as service
from tests.test_approval_foundation import workspace as workspace
from tests.test_controlled_confirmation_review import TOKEN, consent
from tests.test_controlled_confirmation_review import prepared as prepared
from tests.test_controlled_form_process import db as db
from tests.test_multipart_confirmation_fixture import confirmation


def parameters(prepared, **changes):
    item, session, _ = prepared
    return (
        dict(
            request_id=item["id"],
            session_id=session,
            payload_hash=item["payload_hash"],
            payload_version=item["payload_version"],
            token=TOKEN,
        )
        | changes
    )


def launch(tmp_path, data):
    index = len(list(tmp_path.glob("input-*.json")))
    input_path = tmp_path / f"input-{index}.json"
    result = tmp_path / f"result-{index}.json"
    data = data | {"result": str(result)}
    input_path.write_text(json.dumps(data), encoding="utf-8")
    env = os.environ.copy() | {
        "FORM_ADAPTER_LAB": "1",
        "FORM_CONFIRMATION_LAB_ENABLED": "true",
        "OUTBOUND_ENABLED": "false",
        "LEGACY_FORM_DELIVERY_ENABLED": "false",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.confirmation_review_process", str(input_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return process, result


def finish(process):
    try:
        process.communicate(timeout=20)  # Private outputs are never printed.
        return process.returncode
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def wait_marker(processes, paths):
    deadline = time.monotonic() + 20
    while not all(path.exists() for path in paths):
        assert all(p.poll() is None for p in processes), "Synthetic child exited before barrier"
        assert time.monotonic() < deadline, "Synthetic process marker timed out"
        time.sleep(0.02)


def count(db, request_id, name):
    return db.scalar(
        select(func.count())
        .select_from(OutreachAuditEvent)
        .where(
            OutreachAuditEvent.request_id == request_id,
            OutreachAuditEvent.event == name,
        )
    )


def safety(db, request_id):
    # A fresh independent connection proves durable evidence, not a nested savepoint.
    with Session(db.get_bind()) as fresh:
        approval = fresh.get(ApprovalRequest, request_id)
        assert approval is not None and approval.status == "APPROVED"
        for model in (ApprovedFormDispatch, FormDelivery, EmailDelivery):
            assert fresh.scalar(select(func.count()).select_from(model)) == 0


def test_parallel_processes_start_record_and_consume_only_once(auth, prepared, db, tmp_path):
    consent(auth, prepared)
    review_id = None
    for action, event in (
        ("start", service.START),
        ("record", service.RESULT),
        ("consume", service.CONSUMED),
    ):
        release = tmp_path / f"release-{action}"
        marker = tmp_path / f"locked-{action}"
        name = f"confirmation-loser-{action}"
        pairs = [
            launch(
                tmp_path,
                parameters(
                    prepared,
                    action=action,
                    review_id=review_id,
                    before_commit=True,
                    marker=str(marker),
                    commit_release=str(release),
                ),
            )
        ]
        try:
            wait_marker([pairs[0][0]], [marker])
            pairs.append(
                launch(
                    tmp_path,
                    parameters(
                        prepared,
                        action=action,
                        review_id=review_id,
                        application_name=name,
                    ),
                )
            )
            deadline = time.monotonic() + 20
            while True:
                db.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND application_name=:name AND wait_event_type='Lock'"
                    ),
                    {"name": name},
                )
                if waiting:
                    break
                assert pairs[1][0].poll() is None, "Contending process exited before DB lock"
                assert time.monotonic() < deadline, "Row lock contention was not observed"
                time.sleep(0.02)
            release.write_text("go", encoding="utf-8")
            codes = [finish(p) for p, _ in pairs]
            assert sorted(codes) == [0, 3]
            success = json.loads(pairs[codes.index(0)][1].read_text(encoding="utf-8"))["result"]
            if action == "start":
                review_id = success
            elif action == "record":
                assert success["status"] == "REVIEW_REQUIRED" and not success["execution_allowed"]
            else:
                assert success["review_closed"] and not success["execution_allowed"]
            db.expire_all()
            assert count(db, prepared[0]["id"], event) == 1
        finally:
            for process, _ in pairs:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)
    safety(db, prepared[0]["id"])


@pytest.mark.parametrize("action", ["start", "consume"])
def test_process_death_before_and_after_commit(auth, prepared, db, tmp_path, action):
    consent(auth, prepared)
    data = parameters(prepared, action=action)
    event = service.START if action == "start" else service.CONSUMED
    if action == "consume":
        review_id = service.start(
            db,
            prepared[0]["id"],
            prepared[1],
            expected_hash=prepared[0]["payload_hash"],
            expected_version=1,
        )
        service.record(
            db,
            prepared[0]["id"],
            prepared[1],
            review_id,
            html=confirmation(),
            response_url="https://fixture.example/confirm",
            fixture_token=TOKEN,
        )
        data["review_id"] = str(review_id)
    for phase in ("before_commit", "after_commit"):
        marker = tmp_path / phase
        process, _ = launch(tmp_path, data | {phase: True, "marker": str(marker)})
        try:
            wait_marker([process], [marker])
            process.kill()
            finish(process)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        db.expire_all()
        assert count(db, prepared[0]["id"], event) == (0 if phase == "before_commit" else 1)
    # Another process has a fresh pool/session; committed state must reject replay.
    process, output = launch(tmp_path, data)
    assert finish(process) == 3
    assert json.loads(output.read_text(encoding="utf-8"))["rejected"] == 409
    safety(db, prepared[0]["id"])


def test_unknown_survives_new_process_and_cannot_retry(auth, prepared, db, tmp_path):
    consent(auth, prepared)
    process, output = launch(tmp_path, parameters(prepared, action="start"))
    assert finish(process) == 0
    review_id = json.loads(output.read_text(encoding="utf-8"))["result"]
    process, output = launch(
        tmp_path, parameters(prepared, action="record", review_id=review_id, unknown=True)
    )
    assert finish(process) == 0
    result = json.loads(output.read_text(encoding="utf-8"))["result"]
    assert result["status"] == "UNKNOWN" and not result["automatic_retry_allowed"]
    for action in ("start", "record", "consume"):
        process, _ = launch(tmp_path, parameters(prepared, action=action, review_id=review_id))
        assert finish(process) == 3
    db.expire_all()
    assert count(db, prepared[0]["id"], service.RESULT) == 1
    assert count(db, prepared[0]["id"], service.CONSUMED) == 0
    safety(db, prepared[0]["id"])
