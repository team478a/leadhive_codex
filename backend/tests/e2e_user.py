"""Provision/clean only this browser run's temporary account in the dedicated test DB."""

import json
import os
import sys
from datetime import datetime, timezone

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
    EmailDelivery,
    EmailFeedbackEvent,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    InboundEmail,
    InboundMailSettings,
    OutreachDraft,
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
    elif sys.argv[1] in {
        "approval-fixture",
        "completion-fixture",
        "approved-email-fixture",
        "email-feedback-fixture",
        "adapter-fixture",
    }:
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
            email=f"recipient-{project.id.hex}@example.com"
            if sys.argv[1] not in {"approval-fixture", "completion-fixture"}
            else "",
        )
        db.add(company)
        db.flush()
        if sys.argv[1] == "completion-fixture":
            db.add_all(
                [
                    Company(
                        project_id=project.id,
                        source="url",
                        company_name=f"Synthetic batch {index}",
                        domain=f"batch-{index}.example",
                        email="shared@fixture.example",
                    )
                    for index in range(25)
                ]
            )
        if sys.argv[1] == "adapter-fixture":
            company.contact_url = "https://fixture.example/contact"
            sender = db.get(FormSenderSettings, 1)
            if sender is None:
                sender = FormSenderSettings(id=1)
                db.add(sender)
            sender.contact_name, sender.email = "Synthetic Human", "sender@example.com"
            form = FormProfile(
                company_id=company.id,
                form_url=company.contact_url,
                action_url="https://fixture.example/submit",
                fingerprint="a" * 64,
                form_status="READY",
                sales_contact_status="ALLOWED",
                captcha_type="CAPTCHA_NONE",
                confirmation_page=False,
                form_found=True,
                delivery_supported=True,
                is_primary=True,
            )
            db.add(form)
            db.flush()
            db.add(
                FormProfileField(
                    form_profile_id=form.id,
                    name="message",
                    field_type="textarea",
                    required=True,
                    mapped_key="message",
                    confidence=1.0,
                    position=0,
                )
            )
            db.add(
                OutreachDraft(
                    company_id=company.id,
                    channel="form",
                    subject="Synthetic adapter draft",
                    body="Synthetic body only",
                )
            )
        if sys.argv[1] == "email-feedback-fixture":
            draft = OutreachDraft(
                company_id=company.id,
                channel="email",
                subject="Simulated only",
                body="No SMTP call",
            )
            db.add(draft)
            db.flush()
            db.add(
                EmailDelivery(
                    company_id=company.id,
                    draft_id=draft.id,
                    recipient_email=company.email,
                    subject=draft.subject,
                    body=draft.body,
                    status="unknown",
                    scheduled_for=datetime.now(timezone.utc),
                    started_at=datetime.now(timezone.utc),
                    confirmed_at=datetime.now(timezone.utc),
                )
            )
        print(
            json.dumps(
                {
                    "project_id": str(project.id),
                    "company_id": str(company.id),
                    "recipient": company.email,
                }
            )
        )
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
            audited = audited or db.scalar(
                select(EmailFeedbackEvent.id)
                .join(Project)
                .where(Project.user_id == user.id)
                .limit(1)
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
