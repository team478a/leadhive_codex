"""Provision/clean only this browser run's temporary account in the dedicated test DB."""

import json
import os
import sys

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

url = os.environ["TEST_DATABASE_URL"]
if not (make_url(url).database or "").endswith("_test"):
    raise RuntimeError("Browser tests require a dedicated _test database")
os.environ["DATABASE_URL"] = url

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ApprovalRequest,
    AuthSession,
    Company,
    FormSenderSettings,
    InboundEmail,
    InboundMailSettings,
    Project,
    SmtpSettings,
    TargetProfile,
    User,
)
from app.security import password_hasher  # noqa: E402

email = os.environ["E2E_EMAIL"]
if not email.startswith("e2e-") or not email.endswith("@example.com"):
    raise RuntimeError("Only temporary e2e accounts may be modified")
with SessionLocal() as db:
    if sys.argv[1] == "create":
        db.add(
            User(
                email=email,
                password_hash=password_hasher.hash(os.environ["E2E_PASSWORD"]),
                is_admin=not email.startswith("e2e-member-"),
            )
        )
    elif sys.argv[1] == "approval-fixture":
        user = db.scalar(select(User).where(User.email == email))
        profile = db.scalar(select(TargetProfile).where(TargetProfile.is_system).limit(1))
        project = Project(
            user_id=user.id,
            target_profile_id=profile.id,
            project_name="A2 E2E approval",
            sales_objective="Preparation only",
            region="全国",
        )
        db.add(project)
        db.flush()
        company = Company(
            source="url",
            project_id=project.id,
            company_name="A2 E2E Company",
            website_url="https://approval.example",
            domain="approval.example",
        )
        db.add(company)
        db.flush()
        print(json.dumps({"project_id": str(project.id), "company_id": str(company.id)}))
    elif sys.argv[1] == "cleanup":
        db.execute(delete(FormSenderSettings))
        db.execute(delete(SmtpSettings))
        db.execute(delete(InboundEmail))
        db.execute(delete(InboundMailSettings))
        user = db.scalar(select(User).where(User.email == email))
        if user:
            # Immutable audit fixtures cannot be deleted by application credentials.
            # Retain only in the dedicated disposable _test DB; never bypass triggers.
            audited = db.scalar(
                select(ApprovalRequest.id).join(Project).where(Project.user_id == user.id).limit(1)
            )
            if audited:
                db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
                db.commit()
                sys.exit(0)
            for model in (AuthSession, Project, TargetProfile):
                db.execute(delete(model).where(model.user_id == user.id))
            db.delete(user)
    else:
        raise RuntimeError("Expected create or cleanup")
    db.commit()
