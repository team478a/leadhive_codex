"""Private synthetic review process. No network transport or dispatch imports."""

import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.services import controlled_confirmation_review as service
from tests.test_multipart_confirmation_fixture import confirmation


def main():
    if os.environ.get("FORM_ADAPTER_LAB") != "1":
        raise RuntimeError("Explicit test opt-in required")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    with Session(engine) as db:
        if data.get("application_name"):
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": data["application_name"]},
            )
        if data.get("before_commit"):
            original_commit = db.commit

            def pause_commit():
                Path(data["marker"]).write_text("before_commit", encoding="utf-8")
                if data.get("commit_release"):
                    deadline = time.monotonic() + 20
                    while not Path(data["commit_release"]).exists():
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Commit barrier timed out")
                        time.sleep(0.02)
                    return original_commit()
                time.sleep(30)
                raise RuntimeError("Test process must be terminated")

            setattr(db, "commit", pause_commit)
        try:
            request_id, session_id = UUID(data["request_id"]), data["session_id"]
            if data["action"] == "start":
                result = str(
                    service.start(
                        db,
                        request_id,
                        session_id,
                        expected_hash=data["payload_hash"],
                        expected_version=data["payload_version"],
                    )
                )
            elif data["action"] == "record":
                result = service.record(
                    db,
                    request_id,
                    session_id,
                    UUID(data["review_id"]),
                    html=None if data.get("unknown") else confirmation(),
                    response_url="https://fixture.example/confirm",
                    fixture_token=data["token"],
                )
            elif data["action"] == "consume":
                result = service.consume_review_token(
                    db,
                    request_id,
                    session_id,
                    UUID(data["review_id"]),
                    data["token"],
                )
            else:
                raise RuntimeError("Unknown test action")
        except HTTPException as exc:
            Path(data["result"]).write_text(
                json.dumps({"rejected": exc.status_code}), encoding="utf-8"
            )
            return 3
        Path(data["result"]).write_text(json.dumps({"result": result}), encoding="utf-8")
        if data.get("after_commit"):
            Path(data["marker"]).write_text("after_commit", encoding="utf-8")
            time.sleep(30)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never echo private input, child environment, credentials or traceback.
        sys.exit(4)
