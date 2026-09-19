"""Provision/clean only this browser run's temporary account in the dedicated test DB."""

import os
import sys

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

url = os.environ["TEST_DATABASE_URL"]
if not (make_url(url).database or "").endswith("_test"):
    raise RuntimeError("Browser tests require a dedicated _test database")
os.environ["DATABASE_URL"] = url

from app.database import SessionLocal  # noqa: E402
from app.models import AuthSession, Project, TargetProfile, User  # noqa: E402
from app.security import password_hasher  # noqa: E402

email = os.environ["E2E_EMAIL"]
if not email.startswith("e2e-") or not email.endswith("@example.com"):
    raise RuntimeError("Only temporary e2e accounts may be modified")
with SessionLocal() as db:
    if sys.argv[1] == "create":
        db.add(User(email=email, password_hash=password_hasher.hash(os.environ["E2E_PASSWORD"])))
    elif sys.argv[1] == "cleanup":
        user = db.scalar(select(User).where(User.email == email))
        if user:
            for model in (AuthSession, Project, TargetProfile):
                db.execute(delete(model).where(model.user_id == user.id))
            db.delete(user)
    else:
        raise RuntimeError("Expected create or cleanup")
    db.commit()
