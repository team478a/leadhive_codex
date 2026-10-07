"""Synthetic presence fixture, restricted to dedicated E2E accounts and test databases."""

import os
import sys

from sqlalchemy import select
from sqlalchemy.engine import make_url

if not (make_url(os.environ["TEST_DATABASE_URL"]).database or "").endswith("_test"):
    raise RuntimeError("Dedicated test database required")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.database import SessionLocal  # noqa: E402
from app.models import Company, Project, User  # noqa: E402
from app.services.external_presence import capture_url, set_status  # noqa: E402

with SessionLocal() as db:
    project = db.get(Project, sys.argv[1])
    owner = db.get(User, project.user_id)
    if not owner.email.startswith("e2e-") or not owner.email.endswith("@example.com"):
        raise RuntimeError("Temporary E2E account required")
    company = db.scalar(select(Company).where(Company.project_id == project.id))
    capture_url(
        db, project.id, "https://instagram.com/fixture", company.website_url, company=company
    )
    capture_url(
        db,
        project.id,
        "https://beauty.hotpepper.jp/slnH000001",
        company.website_url,
        company=company,
    )
    set_status(
        db, company, "YOUTUBE", "NOT_FOUND", method="EXPLICIT_SEARCH", reason="SEARCH_NO_MATCH"
    )
    set_status(db, company, "FACEBOOK", "ERROR", reason="SEARCH_BUDGET_EXHAUSTED")
    db.commit()
