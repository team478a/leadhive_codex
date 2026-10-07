from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import worker
from app.model_settings import SendingWindow
from app.models import ApprovalRequest, EmailDelivery, FormDelivery, OutreachDraft
from app.services import (
    approved_form,
    approved_form_worker,
    email_delivery,
    form_delivery_result,
    sending_window,
)
from tests.test_approval_foundation import workspace as workspace
from tests.test_approved_form import approved as approved
from tests.test_approved_form import executor as executor
from tests.test_approved_form import reserve
from tests.test_form_approval_preparation import form_source as form_source


@pytest.mark.parametrize(
    "instant, expected",
    [
        ("2026-10-09T22:59:59+00:00", False),  # Saturday 07:59 JST
        ("2026-10-09T23:00:00+00:00", True),
        ("2026-10-10T10:59:59+00:00", True),
        ("2026-10-10T11:00:00+00:00", False),
        ("2026-10-10T23:00:00+00:00", True),  # Sunday too
    ],
)
def test_jst_boundaries_and_weekends(db, instant, expected):
    db.add(SendingWindow(id=1, enabled=True, start_minute=480, end_minute=1200))
    db.commit()
    assert sending_window.allowed(db, datetime.fromisoformat(instant)) is expected


def test_compatibility_and_disabled(db):
    night = datetime(2026, 10, 7, 14, tzinfo=timezone.utc)
    assert sending_window.allowed(db, night)
    db.add(SendingWindow(id=1, enabled=False))
    db.commit()
    assert sending_window.allowed(db, night)


def test_admin_api_and_validation(auth, users, db, client):
    assert auth.get("/api/admin/sending-window").status_code == 404
    users[0].is_admin = True
    db.commit()
    body = {"enabled": True, "start_minute": 480, "end_minute": 1200}
    assert auth.put("/api/admin/sending-window", json=body).status_code == 200
    assert auth.get("/api/admin/sending-window").json()["timezone"] == "Asia/Tokyo"
    for values in [(1200, 480), (480, 480), (-1, 1200), (480, 1441)]:
        assert (
            auth.put(
                "/api/admin/sending-window",
                json=body | dict(zip(("start_minute", "end_minute"), values)),
            ).status_code
            == 422
        )
    client.cookies.clear()
    assert (
        client.put(
            "/api/admin/sending-window", json=body, headers={"Authorization": "Bearer agent-test"}
        ).status_code
        == 403
    )


def test_closed_claims_do_not_take_work(db, monkeypatch):
    monkeypatch.setattr(sending_window, "allowed", lambda *_: False)
    assert worker.claim_email_delivery(db) is None
    assert approved_form.claim(db) is None


def test_late_form_wait_preserves_approval(auth, approved, db, executor, monkeypatch):
    assert reserve(auth, approved).status_code == 201
    claimed = approved_form.claim(db)
    assert claimed is not None
    monkeypatch.setattr(sending_window, "allowed", lambda *_: False)
    assert approved_form_worker.begin(db, claimed.id, claimed.worker_id, None) is None
    db.refresh(claimed)
    assert claimed.status == "queued"
    assert claimed.started_at is None
    assert db.scalar(select(ApprovalRequest)).status == "APPROVED"
    assert db.scalar(select(FormDelivery)) is None


@pytest.mark.parametrize("status", ["running", "unknown", "sent"])
def test_late_email_wait_preserves_final_results(db, workspace, monkeypatch, status):
    monkeypatch.setattr(sending_window, "allowed", lambda *_: False)
    draft = OutreachDraft(
        company_id=workspace[1].id, channel="email", subject="subject", body="body"
    )
    db.add(draft)
    db.flush()
    now = datetime.now(timezone.utc)
    delivery = EmailDelivery(
        draft_id=draft.id,
        company_id=workspace[1].id,
        recipient_email="test@example.com",
        subject="subject",
        body="body",
        status=status,
        worker_id=uuid4(),
        started_at=now,
        scheduled_for=now,
        confirmed_at=now,
    )
    db.add(delivery)
    db.commit()
    assert sending_window.defer_email(db, delivery)
    assert delivery.status == ("queued" if status == "running" else status)
    if status == "running":
        assert delivery.started_at is None and delivery.worker_id is None
    else:
        assert delivery.started_at == now


def test_smtp_boundary_no_connection(monkeypatch):
    def closed():
        raise HTTPException(409, "closed")

    smtp = Mock()
    monkeypatch.setattr(email_delivery, "require_sending_time", closed)
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", smtp)
    with pytest.raises(HTTPException):
        email_delivery.send_with_configuration(None, "id", "x@example.com", "subject", "body")
    smtp.assert_not_called()


def test_form_post_boundary_no_request(monkeypatch):
    def closed():
        raise HTTPException(409, "closed")

    fetcher = Mock()
    monkeypatch.setattr(form_delivery_result, "require_sending_time", closed)
    with pytest.raises(HTTPException):
        form_delivery_result._request_result(fetcher, "POST", "https://example.com/contact", {})
    fetcher.client.stream.assert_not_called()
