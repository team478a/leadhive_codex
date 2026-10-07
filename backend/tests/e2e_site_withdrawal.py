"""Append a site withdrawal in a dedicated E2E project only."""

import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.engine import make_url

if not (make_url(os.environ["TEST_DATABASE_URL"]).database or "").endswith("_test"):
    raise RuntimeError("Dedicated test database required")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.database import SessionLocal  # noqa: E402
from app.models import Company, Project, SiteIdentityReviewEvent, User  # noqa: E402
from app.services.lead_identity import identity_hash  # noqa: E402

with SessionLocal() as db:
    project = db.get(Project, sys.argv[1])
    owner = db.get(User, project.user_id)
    if not owner.email.startswith("e2e-") or not owner.email.endswith("@example.com"):
        raise RuntimeError("Temporary E2E account required")
    company = db.scalar(select(Company).where(Company.project_id == project.id))
    now = datetime.now(timezone.utc)
    db.add(
        SiteIdentityReviewEvent(
            project_id=project.id,
            company_id=company.id,
            actor_user_id=owner.id,
            version=1,
            event_type="REVOKED",
            identity_hash=identity_hash(company),
            source_url=company.website_url,
            observed_name=company.company_name,
            observed_address="",
            observed_phone="",
            evidence_excerpt="合成テストの公式サイト確認を取り消します",
            reasons=[],
            created_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    db.commit()
