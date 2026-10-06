"""Test-only subprocess: claim one synthetic observation job, then exit without GET."""

import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

if __name__ == "__main__":
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (url.database or "").startswith("leadhive_observation_process_") or not (
        url.database or ""
    ).endswith("_test"):
        raise RuntimeError("Dedicated subprocess test DB required")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "cf7_observer_lab"))
    import job_runner

    engine = create_engine(url)

    def sessions():
        return Session(engine)

    print("READY", flush=True)
    assert sys.stdin.readline().strip() == "CLAIM"
    result = job_runner.claim(sessions, UUID(sys.argv[1]), uuid4())
    print("CLAIMED" if result else "NOT_CLAIMED", flush=True)
    engine.dispose()
