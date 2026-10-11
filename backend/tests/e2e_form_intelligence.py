"""Seed deterministic Form Intelligence records in the dedicated browser test DB."""

import os
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import make_url

url = os.environ["TEST_DATABASE_URL"]
if not (make_url(url).database or "").endswith("_test"):
    raise RuntimeError("Browser tests require a dedicated _test database")
os.environ["DATABASE_URL"] = url

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Company,
    FormAnalysisLog,
    FormProfile,
    FormProfileField,
    OutreachDraft,
    Project,
    User,
)
from app.services.form_intelligence.fields import GROUP_REVIEW_MARKER  # noqa: E402

if len(sys.argv) != 3 or sys.argv[1] != "seed":
    raise RuntimeError("Expected: seed <company-id>")

email = os.environ["E2E_EMAIL"]
if not email.startswith("e2e-") or not email.endswith("@example.com"):
    raise RuntimeError("Only temporary e2e accounts may seed Form Intelligence data")

company_id = UUID(sys.argv[2])
now = datetime.now(UTC)

with SessionLocal() as db:
    user = db.scalar(select(User).where(User.email == email))
    company = db.scalar(
        select(Company)
        .join(Project, Project.id == Company.project_id)
        .where(Company.id == company_id, Project.user_id == user.id if user else False)
    )
    if user is None or company is None:
        raise RuntimeError("The E2E company does not belong to the temporary account")

    primary = FormProfile(
        company_id=company.id,
        form_url=f"{company.website_url.rstrip('/')}/contact",
        form_index=0,
        form_status="READY",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        confirmation_page=False,
        is_primary=True,
        form_found=True,
        page_kind="general",
        fingerprint="a" * 64,
        analysis_version="1.0",
        analysis_provider="rule",
        last_analyzed_at=now,
        analysis_duration_ms=42,
        delivery_supported=True,
        review_reason="",
        error_message="",
    )
    secondary = FormProfile(
        company_id=company.id,
        form_url=f"{company.website_url.rstrip('/')}/partner",
        form_index=0,
        form_status="REVIEW_REQUIRED",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_HCAPTCHA",
        confirmation_page=False,
        is_primary=False,
        form_found=True,
        page_kind="partnership",
        fingerprint="b" * 64,
        analysis_version="1.0",
        analysis_provider="rule",
        last_analyzed_at=now,
        analysis_duration_ms=55,
        delivery_supported=True,
        review_reason="CAPTCHAがあるためブラウザでの確認が必要です。",
        error_message="",
    )
    db.add_all([primary, secondary])
    db.flush()
    db.add_all(
        [
            FormProfileField(
                form_profile_id=primary.id,
                position=2,
                name="services[]",
                label="事業内容",
                field_type="checkbox",
                mapped_key="unknown",
                options=[{"label": "SNS運用", "value": "SNS"}, {"label": "OEM", "value": "OEM"}],
            ),
            FormProfileField(
                form_profile_id=secondary.id,
                position=3,
                name="web[]",
                label="お問い合わせ項目 必須" + GROUP_REVIEW_MARKER,
                field_type="checkbox",
                mapped_key="other",
                options=[{"value": "WEB", "label": "WEB支援"}],
            ),
            FormProfileField(
                form_profile_id=secondary.id,
                position=4,
                name="other[]",
                label="お問い合わせ項目 必須" + GROUP_REVIEW_MARKER,
                field_type="checkbox",
                mapped_key="other",
                options=[{"value": "OTHER", "label": "その他"}],
            ),
            FormProfileField(
                form_profile_id=primary.id,
                position=1,
                selector='textarea[name="message"]',
                label="お問い合わせ内容",
                name="message",
                field_type="textarea",
                required=True,
                mapped_key="message",
                confidence=1.0,
                decision_source="DOM",
            ),
            FormProfileField(
                form_profile_id=primary.id,
                position=0,
                selector='input[name="company"]',
                label="会社名",
                name="company",
                field_type="text",
                required=True,
                mapped_key="company_name",
                confidence=0.98,
                decision_source="RULE",
                recommended_value="",
                options=[],
                placeholder="",
                aria_label="",
                surrounding_text="会社名",
            ),
            FormProfileField(
                form_profile_id=secondary.id,
                position=1,
                selector='input[name="reply_method"]',
                label="連絡方法",
                name="reply_method",
                field_type="radio",
                required=True,
                mapped_key="contact_method",
                confidence=0.9,
                decision_source="OPENAI",
                recommended_value="m",
                options=[{"value": "m", "label": "メール"}, {"value": "t", "label": "電話"}],
            ),
            FormProfileField(
                form_profile_id=secondary.id,
                position=2,
                selector='input[name="newsletter"]',
                label="メルマガ登録",
                name="newsletter",
                field_type="checkbox",
                required=False,
                mapped_key="newsletter_consent",
                confidence=0.9,
                decision_source="RULE",
                recommended_value="yes",
                options=[{"value": "yes", "label": "メルマガ登録"}],
            ),
            FormProfileField(
                form_profile_id=secondary.id,
                position=0,
                selector='input[name="department_code"]',
                label="部署コード",
                name="department_code",
                field_type="text",
                required=True,
                mapped_key="unknown",
                confidence=0.4,
                decision_source="RULE",
                recommended_value="",
                options=[],
                placeholder="",
                aria_label="",
                surrounding_text="部署コード",
            ),
            FormAnalysisLog(
                company_id=company.id,
                form_profile_id=primary.id,
                event_type="analysis_completed",
                provider="rule",
                duration_ms=42,
                usage={},
                details={"form_status": "READY"},
            ),
            FormAnalysisLog(
                company_id=company.id,
                form_profile_id=secondary.id,
                event_type="analysis_completed",
                provider="rule",
                duration_ms=55,
                usage={},
                details={"form_status": "REVIEW_REQUIRED"},
            ),
        ]
    )
    db.add_all(
        [
            FormAnalysisLog(
                company_id=company.id,
                event_type="contact_page_found",
                details={
                    "finding": "EXTERNAL_CONTACT_UNVERIFIED",
                    "url": "https://external-contact.example/entry?no=test-only",
                    "source_url": company.website_url,
                    "label": "お問い合わせ",
                    "discovery_method": "OFFICIAL_SITE_LINK",
                },
            ),
            FormAnalysisLog(
                company_id=company.id,
                event_type="analysis_completed",
                details={
                    "finding": "DOM_CONTACT_FORM_NOT_FOUND",
                    "url": f"{company.website_url}/help",
                },
            ),
            FormAnalysisLog(
                company_id=company.id,
                event_type="analysis_completed",
                details={
                    "finding": "EMBEDDED_FORM_UNVERIFIED",
                    "url": f"{company.website_url}/embed",
                },
            ),
            FormAnalysisLog(
                company_id=company.id,
                event_type="analysis_failed",
                details={"finding": "FETCH_FAILED", "reason": "検証用の取得失敗"},
            ),
        ]
    )
    db.add(
        OutreachDraft(
            company_id=company.id,
            channel="form",
            subject="E2E review subject",
            body="E2E review draft body",
        )
    )
    db.commit()
