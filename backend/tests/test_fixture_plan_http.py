"""Opt-in synthetic CF7 TCP/HTTP and process-death specimen, not dispatch."""

import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.services.form_execution_plan import PlanError, plan_hash
from tests.fixture_plan_http import FixtureServer
from tests.fixture_plan_runner import FixtureLedger, FixtureTransport, run_fixture
from tests.test_form_execution_plan import LOCAL, SUBMIT, plan


@pytest.fixture(autouse=True)
def lab_only():
    if os.environ.get("FORM_PLAN_LAB") != "1":
        pytest.skip("Anonymous plan HTTP specimen is opt-in")


def execute(item, ledger, attempt, port, key="fixture-key", **kwargs):
    return run_fixture(
        item,
        ledger,
        attempt,
        key,
        expected_hash=plan_hash(item),
        expected_version=item.payload_version,
        port=port,
        **kwargs,
    )


def store(tmp_path):
    return FixtureLedger(tmp_path / "attempts_fixture_test.sqlite")


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("success", "SUBMITTED"),
        ("ambiguous", "UNKNOWN"),
        ("validation_error", "UNKNOWN"),
        ("mail_sent", "UNKNOWN"),
        ("wrong_form", "UNKNOWN"),
        ("wrong_attempt", "UNKNOWN"),
        ("confirmation", "UNKNOWN"),
        ("malformed", "UNKNOWN"),
        ("duplicate_json", "UNKNOWN"),
        ("oversized", "UNKNOWN"),
        ("wrong_http", "UNKNOWN"),
        ("html", "UNKNOWN"),
        ("redirect", "UNKNOWN"),
        ("disconnect", "UNKNOWN"),
        ("truncated", "UNKNOWN"),
        ("timeout", "UNKNOWN"),
    ],
)
def test_response_and_restart_never_resend(tmp_path, mode, expected):
    item, ledger, attempt = plan(), store(tmp_path), uuid4()
    with FixtureServer(mode) as lab:
        assert execute(item, ledger, attempt, lab.port) == expected
        reopened = FixtureLedger(ledger.path)
        assert reopened.status(attempt) == expected
        for _ in range(3):
            assert execute(item, reopened, attempt, lab.port) == expected
        assert len(lab.posts) == 1
        assert lab.posts[0]["body"] == item.body
        assert lab.posts[0]["field_values"] == item.model_dump(mode="json")["field_values"]
    # The specimen ledger keeps only IDs/digest/status; not sender/message/tokens.
    with ledger.connect() as db:
        assert [c[1] for c in db.execute("PRAGMA table_info(attempts)")] == [
            "attempt_id",
            "request_key",
            "company_id",
            "target",
            "digest",
            "status",
        ]


def test_simultaneous_clients_share_one_attempt(tmp_path):
    item, ledger, attempt = plan(), store(tmp_path), uuid4()
    with FixtureServer() as lab, ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(execute, item, FixtureLedger(ledger.path), attempt, lab.port)
            for _ in range(4)
        ]
        assert all(f.result(timeout=10) in {"UNKNOWN", "SUBMITTED"} for f in futures)
        assert ledger.status(attempt) == "SUBMITTED" and len(lab.posts) == 1


def test_other_key_attempt_or_changed_payload_cannot_retry(tmp_path):
    item, ledger, attempt = plan(), store(tmp_path), uuid4()
    with FixtureServer("ambiguous") as lab:
        assert execute(item, ledger, attempt, lab.port) == "UNKNOWN"
        for candidate, attempt_id, key in [
            (item, attempt, "different"),
            (item, uuid4(), "fixture-key"),
            (item, uuid4(), "different"),
            (plan(body="changed"), attempt, "fixture-key"),
        ]:
            with pytest.raises(PlanError):
                execute(candidate, ledger, attempt_id, lab.port, key)
        assert len(lab.posts) == 1


def test_no_network_until_unknown_is_durable(tmp_path):
    item, ledger, attempt = plan(), store(tmp_path), uuid4()
    with FixtureServer() as lab:

        def check():
            assert FixtureLedger(ledger.path).status(attempt) == "UNKNOWN"
            assert not lab.posts

        assert execute(item, ledger, attempt, lab.port, after_reserve=check) == "SUBMITTED"


def test_response_db_failure_preserves_unknown(tmp_path, monkeypatch):
    item, ledger, attempt = plan(), store(tmp_path), uuid4()

    def fail(_):
        raise sqlite3.OperationalError("synthetic result persistence failure")

    monkeypatch.setattr(ledger, "accepted", fail)
    with FixtureServer() as lab:
        with pytest.raises(sqlite3.OperationalError):
            execute(item, ledger, attempt, lab.port)
        reopened = FixtureLedger(ledger.path)
        assert reopened.status(attempt) == "UNKNOWN"
        assert execute(item, reopened, attempt, lab.port) == "UNKNOWN"
        assert len(lab.posts) == 1


def test_preflight_mismatch_and_js_do_not_create_attempt(tmp_path):
    ledger = store(tmp_path)
    with FixtureServer() as lab:
        with pytest.raises(PlanError):
            run_fixture(
                plan(),
                ledger,
                uuid4(),
                "key",
                expected_hash="0" * 64,
                expected_version=1,
                port=lab.port,
            )
        with pytest.raises(PlanError):
            execute(
                plan(adapter_id="fixture_js_confirmation", steps=(LOCAL, SUBMIT)),
                ledger,
                uuid4(),
                lab.port,
            )
        assert not lab.posts
        with ledger.connect() as db:
            assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0


def test_runner_requires_opt_in(tmp_path, monkeypatch):
    ledger = store(tmp_path)
    monkeypatch.delenv("FORM_PLAN_LAB")
    with pytest.raises(PlanError, match="opt-in"):
        execute(plan(), ledger, uuid4(), 80)


@pytest.mark.parametrize(
    "url,method",
    [
        ("https://other.example/submit", "POST"),
        ("http://fixture.example/submit", "POST"),
        ("https://fixture.example/submit?other=1", "POST"),
        ("https://fixture.example/submit", "GET"),
        ("https://127.0.0.1/submit", "POST"),
        ("https://fixture.example/confirm", "POST"),
    ],
)
def test_transport_denies_unknown_traffic(url, method):
    with FixtureTransport(80) as transport, pytest.raises(PlanError):
        transport.handle_request(httpx.Request(method, url))


@pytest.mark.parametrize("hold_before_post", [False, True])
def test_real_process_loss_stays_unknown_without_retry(tmp_path, hold_before_post):
    item, ledger, attempt = plan(), store(tmp_path), uuid4()
    input_path = tmp_path / "plan.json"
    input_path.write_text(item.model_dump_json(), encoding="utf-8")
    marker = tmp_path / "reserved.txt"
    with FixtureServer("hold_accepted") as lab:
        args = [
            sys.executable,
            "-m",
            "tests.fixture_plan_process",
            str(input_path),
            str(ledger.path),
            str(attempt),
            str(lab.port),
        ]
        if hold_before_post:
            args.append(str(marker))
        process = subprocess.Popen(
            args,
            cwd=Path(__file__).resolve().parents[1],
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            if hold_before_post:
                deadline = time.monotonic() + 15
                while not marker.exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        pytest.fail("Fixture subprocess exited before reservation")
                    time.sleep(0.05)
                assert marker.exists()
            else:
                assert lab.accepted.wait(15), "Subprocess did not reach the local server"
            process.kill()
            process.wait(timeout=10)
            reopened = FixtureLedger(ledger.path)
            assert reopened.status(attempt) == "UNKNOWN"
            assert execute(item, reopened, attempt, lab.port, key="process-fixture") == "UNKNOWN"
            assert len(lab.posts) == (0 if hold_before_post else 1)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
