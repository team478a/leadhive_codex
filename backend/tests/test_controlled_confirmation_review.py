from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import settings
from app.models import ApprovalRequest, FormDelivery, FormProfile, OutreachAuditEvent, ProjectMember
from app.security import COOKIE_NAME, token_digest
from app.services import controlled_confirmation_review as service
from tests.test_approval_foundation import approve, challenge
from tests.test_approval_foundation import workspace as workspace
from tests.test_multipart_confirmation_fixture import confirmation
from tests.test_multipart_human_approval_boundary import create

TOKEN = "PRIVATE-FIXTURE-TOKEN"


@pytest.fixture
def prepared(auth, workspace, db, monkeypatch, legacy_delivery_test_mode):
    monkeypatch.setenv("FORM_ADAPTER_LAB", "1")
    monkeypatch.setattr(settings, "form_confirmation_lab_enabled", True)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)
    company = workspace[1]
    company.contact_url = "https://fixture.example/contact"
    profile = FormProfile(
        company_id=company.id,
        form_url=company.contact_url,
        action_url="https://fixture.example/confirm",
        form_status="READY",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        confirmation_page=True,
        form_found=True,
        delivery_supported=True,
        fingerprint="a" * 64,
        is_primary=True,
    )
    db.add(profile)
    db.commit()
    item = create(auth, workspace)
    session = token_digest(auth.cookies.get(COOKIE_NAME))
    return item, session, profile


def start(db, prepared):
    item, session, _ = prepared
    return service.start(
        db,
        item["id"],
        session,
        expected_hash=item["payload_hash"],
        expected_version=item["payload_version"],
    )


def record(db, prepared, review_id, **changes):
    item, session, _ = prepared
    values = dict(
        html=confirmation(), response_url="https://fixture.example/confirm", fixture_token=TOKEN
    )
    values.update(changes)
    return service.record(db, item["id"], session, review_id, **values)


def consent(auth, prepared):
    assert approve(auth, prepared[0], challenge(auth, prepared[0])).status_code == 200


def test_persisted_claim_and_single_use_token(auth, prepared, db):
    consent(auth, prepared)
    review_id = start(db, prepared)
    db.expire_all()
    with pytest.raises(HTTPException):
        start(db, prepared)
    assert record(db, prepared, review_id)["status"] == "REVIEW_REQUIRED"
    with pytest.raises(HTTPException):
        record(db, prepared, review_id)
    item, session, _ = prepared
    with pytest.raises(HTTPException):
        service.consume_review_token(db, item["id"], session, review_id, "wrong")
    assert service.consume_review_token(db, item["id"], session, review_id, TOKEN) == {
        "review_closed": True,
        "execution_allowed": False,
        "submitted": False,
    }
    db.expire_all()
    with pytest.raises(HTTPException):
        service.consume_review_token(db, item["id"], session, review_id, TOKEN)
    assert db.get(ApprovalRequest, item["id"]).status == "APPROVED"
    rows = db.scalars(
        select(OutreachAuditEvent).where(OutreachAuditEvent.request_id == item["id"])
    ).all()
    assert all(TOKEN not in (row.reason or "") for row in rows)
    assert len([r for r in rows if r.event == service.CONSUMED]) == 1
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == 0


@pytest.mark.parametrize("mode", ["unknown", "changed", "wrong_url"])
def test_untrusted_or_unknown_evidence_never_closes_token(auth, prepared, db, mode):
    consent(auth, prepared)
    review_id = start(db, prepared)
    overrides = {
        "unknown": {"html": None},
        "changed": {"html": confirmation().replace("fixture@example.com", "other@example.com")},
        "wrong_url": {"response_url": "https://external.example/confirm"},
    }[mode]
    result = record(db, prepared, review_id, **overrides)
    assert result["status"] == ("UNKNOWN" if mode == "unknown" else "BLOCKED")
    assert not result["execution_allowed"] and not result["automatic_retry_allowed"]
    with pytest.raises(HTTPException):
        service.consume_review_token(db, prepared[0]["id"], prepared[1], review_id, TOKEN)
    with pytest.raises(HTTPException):
        start(db, prepared)


@pytest.mark.parametrize(
    "fault",
    ["no_approval", "flag", "outbound", "session", "hash", "version", "suppressed", "captcha"],
)
def test_start_guards(auth, prepared, db, monkeypatch, fault, workspace):
    if fault != "no_approval":
        consent(auth, prepared)
    item, session, profile = prepared
    values = dict(expected_hash=item["payload_hash"], expected_version=item["payload_version"])
    if fault == "flag":
        monkeypatch.setattr(settings, "form_confirmation_lab_enabled", False)
    elif fault == "outbound":
        monkeypatch.setattr(settings, "outbound_enabled", True)
    elif fault == "session":
        session = "invalid-agent-credential"
    elif fault == "hash":
        values["expected_hash"] = "0" * 64
    elif fault == "version":
        values["expected_version"] = True
    elif fault == "suppressed":
        workspace[1].do_not_contact = True
        db.commit()
    elif fault == "captcha":
        profile.captcha_type = "CAPTCHA_RECAPTCHA"
        db.commit()
    with pytest.raises(HTTPException):
        service.start(db, item["id"], session, **values)
    assert not db.scalar(
        select(OutreachAuditEvent).where(OutreachAuditEvent.event == service.START)
    )


def test_expiry_and_wrong_review_id(auth, prepared, db, monkeypatch):
    consent(auth, prepared)
    review_id = start(db, prepared)
    with pytest.raises(HTTPException):
        record(db, prepared, uuid4())
    record(db, prepared, review_id)
    current = service.now()
    monkeypatch.setattr(service, "now", lambda: current + timedelta(minutes=6))
    with pytest.raises(HTTPException):
        service.consume_review_token(db, prepared[0]["id"], prepared[1], review_id, TOKEN)


def test_viewer_and_other_project_session_rejected(auth, prepared, db, users, workspace):
    from app.models import AuthSession

    consent(auth, prepared)
    session = AuthSession(
        token_hash="f" * 64, user_id=users[1].id, expires_at=service.now() + timedelta(hours=1)
    )
    db.add(session)
    db.commit()
    for member in (False, True):
        if member:
            db.add(ProjectMember(project_id=workspace[0].id, user_id=users[1].id, role="viewer"))
            db.commit()
        with pytest.raises(HTTPException):
            service.start(
                db,
                prepared[0]["id"],
                session.token_hash,
                expected_hash=prepared[0]["payload_hash"],
                expected_version=1,
            )


def test_transaction_failure_does_not_leave_start_claim(auth, prepared, db, monkeypatch):
    consent(auth, prepared)
    original = db.commit

    def failed_commit():
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(db, "commit", failed_commit)
    with pytest.raises(RuntimeError):
        start(db, prepared)
    db.rollback()
    monkeypatch.setattr(db, "commit", original)
    assert not db.scalar(
        select(OutreachAuditEvent).where(OutreachAuditEvent.event == service.START)
    )
    assert start(db, prepared)


def test_default_off():
    from app.config import Settings

    assert Settings.model_fields["form_confirmation_lab_enabled"].default is False
