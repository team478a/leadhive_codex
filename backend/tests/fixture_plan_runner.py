"""Lab-only CF7-shaped exchange; never import from app or consume an approval.

The SQLite ledger is a disposable specimen, not LeadHive's production ledger.
Every network connection is pinned to loopback through the supplied port.
"""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import UUID

import httpx

from app.services.form_execution_plan import (
    ExecutionPlan,
    FixtureResult,
    PlanError,
    classify_fixture_result,
    plan_hash,
    validate_plan,
)


class FixtureLedger:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.name.endswith("_fixture_test.sqlite"):
            raise ValueError("Disposable fixture ledger path required")
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                company_id TEXT UNIQUE NOT NULL, target TEXT UNIQUE NOT NULL,
                digest TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('UNKNOWN','SUBMITTED'))
            )""")

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            yield db

    def reserve(self, plan, attempt_id, key):
        digest = plan_hash(plan)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT attempt_id,digest FROM attempts WHERE request_key=?", (key,)
            ).fetchone()
            if existing:
                if existing != (str(attempt_id), digest):
                    raise PlanError("Fixture idempotency key conflict")
                return False
            try:
                db.execute(
                    "INSERT INTO attempts VALUES (?,?,?,?,?,?)",
                    (
                        str(attempt_id),
                        key,
                        str(plan.company_id),
                        plan.form_url,
                        digest,
                        "UNKNOWN",
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PlanError("Fixture duplicate attempt blocked") from exc
        # Committed before any client/socket creation, including process death.
        return True

    def status(self, attempt_id):
        with self.connect() as db:
            return db.execute(
                "SELECT status FROM attempts WHERE attempt_id=?", (str(attempt_id),)
            ).fetchone()[0]

    def accepted(self, attempt_id):
        with self.connect() as db:
            db.execute(
                "UPDATE attempts SET status='SUBMITTED' WHERE attempt_id=? AND status='UNKNOWN'",
                (str(attempt_id),),
            )


class FixtureTransport(httpx.BaseTransport):
    def __init__(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid loopback port")
        self.port = port
        self.inner = httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        if str(request.url) != "https://fixture.example/submit" or request.method != "POST":
            raise PlanError("Fixture transport refuses unknown traffic")
        local = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        forwarded = httpx.Request(
            request.method,
            local,
            headers=request.headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return self.inner.handle_request(forwarded)

    def close(self):
        self.inner.close()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous duplicate JSON key")
        result[key] = value
    return result


def run_fixture(
    plan: ExecutionPlan,
    ledger: FixtureLedger,
    attempt_id: UUID,
    key: str,
    *,
    expected_hash: str,
    expected_version: int,
    port: int,
    after_reserve=None,
):
    if os.environ.get("FORM_PLAN_LAB") != "1":
        raise PlanError("Fixture exchange requires explicit lab opt-in")
    validate_plan(plan, plan, expected_hash=expected_hash, expected_version=expected_version)
    if plan.adapter_id != "fixture_cf7":
        raise PlanError("Only the single-stage synthetic CF7 contract is executable")
    if not isinstance(key, str) or not 1 <= len(key) <= 100 or type(attempt_id) is not UUID:
        raise PlanError("Invalid fixture attempt identity")
    if type(port) is not int or not 1 <= port <= 65535:
        raise PlanError("Invalid fixture loopback port")
    payload = plan.model_dump(mode="json") | {"attempt_id": str(attempt_id)}
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > 64000:
        raise PlanError("Fixture request exceeds limit")
    if not ledger.reserve(plan, attempt_id, key):
        return ledger.status(attempt_id)
    if after_reserve:
        after_reserve()  # Test-only process synchronization; never an agent tool.
    try:
        with httpx.Client(
            transport=FixtureTransport(port), trust_env=False, timeout=0.5, follow_redirects=False
        ) as client:
            with client.stream(
                "POST",
                plan.steps[0].url,
                content=encoded,
                headers={"Content-Type": "application/json"},
            ) as response:
                if (
                    response.status_code != 200
                    or response.headers.get("content-type", "").split(";")[0].strip().lower()
                    != "application/json"
                ):
                    return "UNKNOWN"
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 64000:
                        return "UNKNOWN"
                parsed = json.loads(raw, object_pairs_hook=unique_object)
                evidence = FixtureResult.model_validate_json(json.dumps(parsed))
                if (
                    classify_fixture_result(evidence, form_id=plan.form_id, attempt_id=attempt_id)
                    == "SUBMITTED"
                ):
                    ledger.accepted(attempt_id)
    except (httpx.HTTPError, ValueError):
        pass  # Even a validation error after POST cannot prove non-acceptance.
    return ledger.status(attempt_id)
