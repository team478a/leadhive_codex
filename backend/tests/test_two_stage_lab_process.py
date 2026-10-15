"""Kill/restart actual HTTP workflow against a disposable committed database."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutreachAuditEvent
from app.services import controlled_confirmation_review as review
from tests.test_approval_foundation import workspace as workspace
from tests.test_controlled_form_process import db as db
from tests.test_form_approval_preparation import form_source as form_source
from tests.test_two_stage_lab_http import approved, safety
from tests.test_two_stage_lab_http import source as source
from tests.two_stage_lab_http import TwoStageServer
from tests.two_stage_lab_runner import FINAL, FIRST, RESULT


def launch(tmp_path, data, label):
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / (label + ".json")
    config.write_text(json.dumps(data), encoding="utf-8")
    env = os.environ.copy() | {
        "PYTHONPATH": str(root),
        "FORM_ADAPTER_LAB": "1",
        "FORM_CONFIRMATION_LAB_ENABLED": "true",
        "OUTBOUND_ENABLED": "false",
        "LEGACY_FORM_DELIVERY_ENABLED": "false",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "tests.two_stage_lab_process", str(config)],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.parametrize(
    "checkpoint,event,posts,recorded,consumed,finished",
    [
        ("before_commit", review.START, 0, False, False, False),
        ("after_commit", review.START, 0, False, False, False),
        ("before_commit", FIRST, 0, False, False, False),
        ("before_confirm_post", None, 0, False, False, False),
        ("after_confirm_response", None, 1, False, False, False),
        ("before_commit", FINAL, 1, True, False, False),
        ("before_submit_post", None, 1, True, True, False),
        ("after_submit_response", None, 2, True, True, False),
        ("before_commit", RESULT, 2, True, True, False),
        ("after_commit", RESULT, 2, True, True, True),
        ("server_confirm_received", None, 1, False, False, False),
        ("server_submit_received", None, 2, True, True, False),
    ],
)
def test_kill_restart_never_replays_committed_attempt(
    auth, source, db, tmp_path, checkpoint, event, posts, recorded, consumed, finished
):
    approved(auth, source)
    item, session, _ = source
    marker, result = tmp_path / "ready.txt", tmp_path / "result.json"
    uncommitted_start = checkpoint == "before_commit" and event == review.START
    mode = {
        "server_confirm_received": "hold_confirm",
        "server_submit_received": "hold_submit",
    }.get(checkpoint, "success")
    with TwoStageServer(mode) as lab:
        data = {
            "request_id": item["id"],
            "session_id": session,
            "port": lab.port,
            "marker": str(marker),
            "result": str(result),
            "checkpoint": checkpoint,
            "event": event,
        }
        process = launch(tmp_path, data, "first")
        try:
            deadline = time.monotonic() + 20

            def reached():
                return lab.response_held.is_set() if mode != "success" else marker.exists()

            while not reached() and time.monotonic() < deadline:
                assert process.poll() is None, "Child exited before checkpoint"
                time.sleep(0.02)
            assert reached(), "Checkpoint was not reached"
            process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)  # Never print child credentials or output.
        lab.response_release.set()

        assert len(lab.posts) == posts
        assert lab.accepted == (1 if posts == 2 else 0)
        with Session(db.get_bind()) as independent:
            events = independent.scalars(
                select(OutreachAuditEvent).where(OutreachAuditEvent.request_id == item["id"])
            ).all()
            names = [e.event for e in events]
            assert names.count(review.START) == (0 if uncommitted_start else 1)
            assert names.count(FIRST) == int(posts > 0 or checkpoint == "before_confirm_post")
            assert names.count(review.RESULT) == int(recorded)
            assert names.count(review.CONSUMED) == int(consumed)
            assert names.count(FINAL) == int(consumed)  # Same atomic transaction.
            assert names.count(RESULT) == int(finished)
            if finished:
                assert next(e.reason for e in events if e.event == RESULT) == "FIXTURE_SUBMITTED"
            safety(independent, item)

        # New process, new DB connection, same approved payload and running server.
        restart = launch(tmp_path, data | {"checkpoint": None, "event": None}, "restart")
        try:
            restart.communicate(timeout=20)
            assert restart.returncode == (0 if uncommitted_start else 3)
        finally:
            if restart.poll() is None:
                restart.kill()
            restart.communicate(timeout=10)
        outcome = json.loads(result.read_text(encoding="utf-8"))
        assert outcome == (
            {"result": "FIXTURE_SUBMITTED"} if uncommitted_start else {"rejected": 409}
        )
        assert len(lab.posts) == (2 if uncommitted_start else posts)
        assert lab.accepted == (1 if uncommitted_start or posts == 2 else 0)
        with Session(db.get_bind()) as independent:
            safety(independent, item)
