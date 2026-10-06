"""CF7 browser fixture. Only in a disposable, dedicated P3 DB; retain audit rows."""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import make_url

url = os.environ["TEST_DATABASE_URL"]
name = make_url(url).database or ""
if (
    os.environ.get("CF7_E2E_DISPOSABLE_DATABASE") != "true"
    or not name.startswith("leadhive_cf7_p3_e2e_")
    or not name.endswith("_test")
):
    raise RuntimeError("CF7 browser fixture requires its dedicated disposable database")
os.environ["DATABASE_URL"] = url
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    CF7Observation,
    Company,
    FormProfile,
    FormSenderSettings,
    OutreachDraft,
    Project,
    User,
)
from app.services import cf7_candidate_preparation as service  # noqa: E402
from app.services import human_approval as approval  # noqa: E402
from app.services.cf7_candidate_contract import digest  # noqa: E402
from tests.test_cf7_candidate_contract import candidate  # noqa: E402

with SessionLocal() as db:
    email = os.environ["E2E_EMAIL"]
    if not email.startswith("e2e-cf7-") or not email.endswith("@example.com"):
        raise RuntimeError("Expected dedicated browser fixture account")
    company = db.scalar(
        select(Company)
        .join(Project)
        .join(User)
        .where(
            Company.id == UUID(sys.argv[2]),
            User.email == email,
        )
    )
    if not company:
        raise RuntimeError("Fixture ownership mismatch")
    if sys.argv[1] == "change-draft":
        draft = db.scalar(select(OutreachDraft).where(OutreachDraft.company_id == company.id))
        draft.body = "変更後の日本語本文\n再承認が必要です"
    elif sys.argv[1] == "seed":
        raw = candidate().model_dump(mode="json")
        raw["controls"][-1]["label"] = "問い合わせ内容への同意"
        raw["controls"].append(
            {
                "name": "newsletter",
                "kind": "checkbox",
                "required": False,
                "label": "ニュース配信を購読する",
                "checkbox_value": "subscribe",
            }
        )
        company.company_name = "CF7 Browser Fixture"
        company.contact_url = raw["form_url"]
        profile = FormProfile(
            company_id=company.id,
            form_url=raw["form_url"],
            fingerprint=raw["dom_fingerprint"],
            form_status="REVIEW_REQUIRED",
            sales_contact_status="ALLOWED",
            captcha_type="CAPTCHA_NONE",
            form_found=True,
            confirmation_page=False,
            delivery_supported=False,
            is_primary=True,
        )
        draft = OutreachDraft(
            company_id=company.id,
            channel="form",
            subject="",
            body="検証用の日本語本文\n送信しません",
        )
        sender = db.get(FormSenderSettings, 1)
        if sender is None:
            sender = FormSenderSettings(id=1)
            db.add(sender)
        sender.contact_name, sender.email = "Synthetic Human", "sender@example.com"
        db.add_all([profile, draft])
        db.flush()
        structure = {k: raw[k] for k in service.CF7Structure.model_fields}
        evidence = {
            "structure": structure,
            "profile_source_hash": service.profile_source_hash(db, profile),
        }
        observed = approval.now()
        user = db.scalar(select(User).where(User.email == email))
        db.add(
            CF7Observation(
                project_id=company.project_id,
                company_id=company.id,
                form_profile_id=profile.id,
                source_kind="CONTROLLED_FIXTURE",
                observer_version="cf7-controlled-v1",
                observed_at=observed,
                expires_at=observed + timedelta(hours=1),
                evidence_snapshot=evidence,
                evidence_hash=digest(evidence),
                created_by_user_id=user.id,
            )
        )
        print(json.dumps({"draft_id": str(draft.id)}))
    else:
        raise RuntimeError("Expected seed or change-draft")
    db.commit()
