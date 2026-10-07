"""Synthetic stored text only, in a dedicated temporary E2E project."""

import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import make_url

if not (make_url(os.environ["TEST_DATABASE_URL"]).database or "").endswith("_test"):
    raise RuntimeError("Dedicated test database required")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.database import SessionLocal  # noqa: E402
from app.models import Company, Project, User  # noqa: E402

with SessionLocal() as db:
    project = db.get(Project, sys.argv[1])
    owner = db.get(User, project.user_id)
    if not owner.email.startswith("e2e-") or not owner.email.endswith("@example.com"):
        raise RuntimeError("Temporary E2E account required")
    company = db.scalar(select(Company).where(Company.project_id == project.id))
    company.website_text = "当社は美容院として地域のお客様へヘアケアを提供しています。"
    company.scraped_urls = [company.website_url]
    company.scraped_at = datetime.now(timezone.utc)
    company.analysis_status = "completed"
    db.commit()
