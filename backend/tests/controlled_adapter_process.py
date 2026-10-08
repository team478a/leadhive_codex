"""Test-only child process. Never run through the application worker registry."""

import os
import sys
import threading
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.database import engine
from app.services import approved_form, controlled_form_execution
from tests.controlled_adapter_transport import LabTransport

if os.environ.get("FORM_ADAPTER_LAB") != "1":
    raise RuntimeError("Test opt-in required")


def committed(attempt_id):
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(str(attempt_id), encoding="utf-8")
        threading.Event().wait(30)


with Session(engine) as db:
    claimed = approved_form.claim(db, controlled_lab=True)
    if claimed is None:
        sys.exit(0)
    if claimed.id != UUID(sys.argv[1]):
        raise RuntimeError("No matching synthetic reservation")
    controlled_form_execution.run(db, claimed, LabTransport(int(sys.argv[2]), committed))
