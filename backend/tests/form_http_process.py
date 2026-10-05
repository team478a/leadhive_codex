"""Dedicated lab subprocess; never run with an application/preview database."""

import json
import os
import sys
from datetime import datetime

from sqlalchemy.engine import make_url

if (
    os.environ.get("FORM_HTTP_LAB") != "1"
    or make_url(os.environ["TEST_DATABASE_URL"]).database != "leadhive_form_http_test"
):
    raise RuntimeError("Requires the dedicated form HTTP lab database")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services import approved_form, approved_form_worker, human_approval  # noqa: E402
from tests.form_http_lab import local_transport  # noqa: E402

settings.outbound_enabled = True
settings.human_approved_form_enabled = True
settings.legacy_form_delivery_enabled = False
fixed_time = datetime.fromisoformat(os.environ["FORM_HTTP_LAB_CLOCK"])
human_approval.now = lambda: fixed_time

with local_transport(int(os.environ["FORM_HTTP_LAB_PORT"])), SessionLocal() as db:
    row = approved_form.claim(db)
    if sys.argv[1] == "dispatch" and row:
        approved_form_worker.run(db, row)
    print(json.dumps({"id": str(row.id) if row else None}), flush=True)
