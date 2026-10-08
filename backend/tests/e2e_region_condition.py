"""Verified address fixture for a temporary E2E project; no external access."""

import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import make_url

if not (make_url(os.environ["TEST_DATABASE_URL"]).database or "").endswith("_test"):
    raise RuntimeError("Dedicated test database required")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.database import SessionLocal  # noqa: E402
from app.models import Company, LeadSiteEvidence, Project, User  # noqa: E402
from app.services.lead_identity import identity_hash  # noqa: E402

with SessionLocal() as db:
    project = db.get(Project, sys.argv[1])
    owner = db.get(User, project.user_id)
    if not owner.email.startswith("e2e-") or not owner.email.endswith("@example.com"):
        raise RuntimeError("Temporary E2E account required")
    company = db.scalar(select(Company).where(Company.project_id == project.id))
    company.prefecture, company.city = "兵庫県", "姫路市"
    company.address = "兵庫県姫路市本町1"
    company.website_text = company.company_name + " 所在地 " + company.address
    db.add(
        LeadSiteEvidence(
            company_id=company.id,
            identity_hash=identity_hash(company),
            confidence="CONFIRMED",
            reasons=["ADDRESS_MATCH", "COMPANY_NAME_MATCH"],
            source_url=company.website_url,
            observed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
