"""One-job synthetic runner CLI. Not a daemon, scheduler or real-site worker."""

import argparse
import json
import os
import re
import signal
import ssl
import sys
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def emit(code: str) -> None:
    print(json.dumps({"runner": "owned-fixture-only", "code": code}), flush=True)


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        emit("RUNNER_ARGUMENTS_REJECTED")
        raise SystemExit(2)


def main() -> int:
    parser = Arguments(
        description="Run one existing managed observation job against a synthetic loopback TLS fixture."
    )
    parser.add_argument("--owned-fixture", action="store_true", required=True)
    parser.add_argument("--job-id", type=UUID, required=True)
    parser.add_argument(
        "--scenario",
        choices=(
            "success",
            "robots-denied",
            "http-rejected",
            "response-invalid",
            "timeout",
            "tls-failed",
        ),
        default="success",
    )
    args = parser.parse_args()
    try:
        url = make_url(os.environ.get("TEST_DATABASE_URL", ""))
        if (
            url.drivername != "postgresql+psycopg"
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or bool(url.query)
            or not re.fullmatch(
                r"leadhive_observation_run_[0-9a-f]{12,24}_test", url.database or ""
            )
            or (
                os.environ.get("DATABASE_URL")
                and make_url(os.environ["DATABASE_URL"]) != url
            )
        ):
            emit("RUNNER_CONFIGURATION_REJECTED")
            return 2
    except (ValueError, SQLAlchemyError):
        emit("RUNNER_CONFIGURATION_REJECTED")
        return 2
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import job_runner
    from app.services.form_observation_jobs import guard
    from fastapi import HTTPException
    from owned_fixture import OwnedFixture

    engine = create_engine(
        url, hide_parameters=True, connect_args={"connect_timeout": 5}
    )
    stop = Event()
    previous = {}

    def request_stop(*_):
        stop.set()

    def sessions():
        return Session(engine)

    try:
        with sessions() as db:
            guard(db)
            if db.scalar(
                text("SELECT current_database()")
            ) != url.database or not db.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_observation_job_reason' "
                    "AND conrelid='form_observation_job_events'::regclass "
                    "AND position('RUNNER_STOPPED' in pg_get_constraintdef(oid)) > 0)"
                )
            ):
                emit("RUNNER_CONFIGURATION_REJECTED")
                return 2
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, request_stop)
        if stop.is_set():
            emit("RUNNER_STOPPED")
            return 4
        binding = job_runner.claim(sessions, args.job_id, uuid4())
        if binding is None:
            emit("JOB_NOT_CLAIMED")
            return 2
        emit("JOB_CLAIMED")
        with OwnedFixture(args.scenario) as fixture:
            context = (
                ssl.create_default_context()
                if args.scenario == "tls-failed"
                else fixture.lab.context
            )
            result = job_runner.run(sessions, binding, context=context, stop=stop)
        if result:
            emit("DIAGNOSTIC_SAVED")
            return 0
        emit("RUNNER_STOPPED" if stop.is_set() else "DIAGNOSTIC_FAILED")
        return 4 if stop.is_set() else 3
    except (HTTPException, ValueError):
        emit("RUNNER_CONFIGURATION_REJECTED")
        return 2
    except SQLAlchemyError:
        emit("DATABASE_UNAVAILABLE")
        return 5
    except OSError:
        emit("RUNNER_FIXTURE_FAILED")
        return 5
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        engine.dispose()


if __name__ == "__main__":
    # Unexpected failures must not print raw exceptions/DSNs/website contents.
    sys.excepthook = lambda *_: emit("RUNNER_INTERNAL_ERROR")
    raise SystemExit(main())
