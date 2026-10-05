"""Lab subprocess only; no app config, DB, principal, or worker connection."""

import json
import os
import sys
import threading
from pathlib import Path
from uuid import UUID

from app.services.form_execution_plan import ExecutionPlan, plan_hash
from tests.fixture_plan_runner import FixtureLedger, run_fixture

if os.environ.get("FORM_PLAN_LAB") != "1":
    raise RuntimeError("Fixture process requires explicit lab opt-in")

plan = ExecutionPlan.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8"))


def reserved():
    if len(sys.argv) > 5:
        Path(sys.argv[5]).write_text("reserved", encoding="utf-8")
        threading.Event().wait(30)


print(
    json.dumps(
        {
            "status": run_fixture(
                plan,
                FixtureLedger(sys.argv[2]),
                UUID(sys.argv[3]),
                "process-fixture",
                expected_hash=plan_hash(plan),
                expected_version=1,
                port=int(sys.argv[4]),
                after_reserve=reserved,
            )
        }
    ),
    flush=True,
)
