"""Private child process for forced-death tests; only fixed loopback fixture traffic."""

import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine
from app.models import OutreachAuditEvent
from tests.two_stage_lab_http import TwoStageTransport
from tests.two_stage_lab_runner import run


def main():
    if os.environ.get("FORM_ADAPTER_LAB") != "1":
        raise RuntimeError("Explicit test opt-in required")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    request_id = UUID(data["request_id"])

    def pause(point):
        if data.get("checkpoint") == point:
            Path(data["marker"]).write_text("ready", encoding="utf-8")
            time.sleep(30)
            raise RuntimeError("Test process must be terminated")

    class PausingSession(Session):
        def commit(self):
            names = set(
                self.scalars(
                    select(OutreachAuditEvent.event).where(
                        OutreachAuditEvent.request_id == request_id
                    )
                ).all()
            )
            target = data.get("event")
            if target in names:
                pause("before_commit")
            super().commit()
            if target in names:
                pause("after_commit")

    class Transport(TwoStageTransport):
        def submit(self, plan, attempt, token):
            result = super().submit(plan, attempt, token)
            pause("after_submit_response")
            return result

    transport = Transport(
        data["port"],
        before_post=lambda stage: pause("before_" + stage + "_post"),
        after_confirm=lambda: pause("after_confirm_response"),
        timeout=30,
    )
    with PausingSession(engine) as db:
        try:
            result = run(db, request_id, data["session_id"], transport)
        except HTTPException as exc:
            Path(data["result"]).write_text(
                json.dumps({"rejected": exc.status_code}), encoding="utf-8"
            )
            return 3
        Path(data["result"]).write_text(json.dumps({"result": result}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never expose private arguments, session identifiers or credentials.
        sys.exit(4)
