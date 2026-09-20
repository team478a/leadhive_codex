from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import worker
from app.models import (
    Activity,
    Company,
    EmailDelivery,
    Notification,
    OutreachDraft,
    OutreachDraftApproval,
    SmtpSettings,
)
from app.services.email_delivery import EmailDeliveryError


def make_draft(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "メール送信テスト",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援サービスを案内する",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://delivery.example"]},
    )
    company_data = auth.get(f"/api/projects/{project['id']}/companies").json()[0]
    company = db.get(Company, company_data["id"])
    company.email = "contact@delivery.example"
    draft = OutreachDraft(
        company_id=company.id,
        channel="email",
        subject="サービスのご相談",
        body="貴社へサービスのご案内です。短時間の情報交換はいかがでしょうか。",
        ai_provider="fake",
        ai_model="fake-v1",
    )
    db.add(draft)
    db.commit()
    return project, company, draft


def test_approved_email_delivery_snapshots_sends_and_records_activity(auth, db, monkeypatch):
    _, company, draft = make_draft(auth, db)
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/email-delivery",
            json={"recipient_email": company.email, "confirmed": False},
        ).status_code
        == 422
    )
    created = auth.post(
        f"/api/outreach-drafts/{draft.id}/email-delivery",
        json={"recipient_email": company.email, "confirmed": True},
    )
    assert created.status_code == 202
    delivery = created.json()
    assert delivery["status"] == "queued"
    assert delivery["subject"] == draft.subject
    approval = auth.get(f"/api/outreach-drafts/{draft.id}/approvals").json()
    assert approval[0]["approval_type"] == "email" and approval[0]["body"] == draft.body
    assert db.scalar(
        select(OutreachDraftApproval).where(OutreachDraftApproval.draft_id == draft.id)
    )
    overview = auth.get(f"/api/projects/{company.project_id}/email-deliveries").json()
    assert overview["queued_count"] == 1
    assert overview["items"][0]["company_name"] == company.company_name
    draft.subject = "送信後に編集した件名"
    db.commit()
    sent = []
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "send_email", lambda *args: sent.append(args))
    assert worker.run_once()
    result = auth.get(f"/api/outreach-drafts/{draft.id}/email-delivery").json()
    assert result["status"] == "sent" and result["sent_at"]
    assert (
        auth.get(f"/api/projects/{company.project_id}/email-deliveries").json()["sent_count"] == 1
    )
    assert sent[0][2] == company.email and sent[0][3] == "サービスのご相談"
    db.refresh(company)
    assert company.status == "approached"
    company.status = "replied"
    db.commit()
    effectiveness = auth.get("/api/outreach-effectiveness-analytics", params={"days": 30})
    assert effectiveness.status_code == 200
    assert effectiveness.json()["items"] == [
        {
            "approval_type": "email",
            "subject": "サービスのご相談",
            "approvals": 1,
            "replied": 1,
            "meetings": 0,
            "won": 0,
            "reply_rate": 100.0,
        }
    ]
    activity = db.scalar(
        select(Activity).where(Activity.company_id == company.id, Activity.activity_type == "email")
    )
    assert activity is not None
    assert "メール送信" in activity.note
    status_activity = db.scalar(
        select(Activity).where(
            Activity.company_id == company.id,
            Activity.activity_type == "status_change",
        )
    )
    assert status_activity is not None and "アプローチ済" in status_activity.note
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/email-delivery",
            json={"recipient_email": company.email, "confirmed": True},
        ).status_code
        == 409
    )


def test_email_delivery_failure_retry_cancel_and_access(auth, users, db, monkeypatch):
    project, company, draft = make_draft(auth, db)
    created = auth.post(
        f"/api/outreach-drafts/{draft.id}/email-delivery",
        json={"recipient_email": company.email, "confirmed": True},
    )
    delivery_id = created.json()["id"]
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(
        worker,
        "send_email",
        lambda *_args: (_ for _ in ()).throw(EmailDeliveryError("メール送信に失敗しました。")),
    )
    assert worker.run_once()
    failed = auth.get(f"/api/outreach-drafts/{draft.id}/email-delivery").json()
    assert failed["status"] == "failed" and failed["error_message"] == "メール送信に失敗しました。"
    notifications = auth.get("/api/notifications", params={"unread_only": True}).json()
    email_notifications = [
        item for item in notifications if item["notification_type"] == "email_delivery_failed"
    ]
    assert len(email_notifications) == 1
    assert email_notifications[0]["email_delivery_id"] == delivery_id
    assert email_notifications[0]["company_id"] == str(company.id)
    assert db.scalar(select(Notification).where(Notification.email_delivery_id == delivery_id))
    assert (
        auth.post(
            f"/api/email-deliveries/{delivery_id}/retry", json={"confirmed": False}
        ).status_code
        == 422
    )
    retried = auth.post(f"/api/email-deliveries/{delivery_id}/retry", json={"confirmed": True})
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    cancelled = auth.post(f"/api/email-deliveries/{delivery_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"

    auth.post(
        f"/api/projects/{project['id']}/members",
        json={"email": users[1].email, "role": "viewer"},
    )
    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/outreach-drafts/{draft.id}/email-delivery").status_code == 200
    assert (
        auth.post(
            f"/api/email-deliveries/{delivery_id}/retry", json={"confirmed": True}
        ).status_code
        == 404
    )


def test_email_delivery_keeps_advanced_sales_status(auth, db, monkeypatch):
    _, company, draft = make_draft(auth, db)
    company.status = "replied"
    db.commit()
    auth.post(
        f"/api/outreach-drafts/{draft.id}/email-delivery",
        json={"recipient_email": company.email, "confirmed": True},
    )
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "send_email", lambda *_args: None)
    assert worker.run_once()
    db.refresh(company)
    assert company.status == "replied"
    assert not db.scalar(
        select(Activity).where(
            Activity.company_id == company.id,
            Activity.activity_type == "status_change",
        )
    )


def test_email_delivery_rejects_unknown_recipient_and_contact_suppression(auth, db):
    _, company, draft = make_draft(auth, db)
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/email-delivery",
            json={"recipient_email": "unknown@example.com", "confirmed": True},
        ).status_code
        == 409
    )
    company.do_not_contact = True
    db.commit()
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/email-delivery",
            json={"recipient_email": company.email, "confirmed": True},
        ).status_code
        == 409
    )


def test_email_delivery_respects_daily_limit_and_minimum_interval(auth, db):
    _, company, draft = make_draft(auth, db)
    now = datetime.now(timezone.utc)
    sent = EmailDelivery(
        draft_id=draft.id,
        company_id=company.id,
        recipient_email=company.email,
        recipient_name=company.company_name,
        subject=draft.subject,
        body=draft.body,
        status="sent",
        scheduled_for=now - timedelta(minutes=2),
        confirmed_at=now - timedelta(minutes=2),
        sent_at=now - timedelta(seconds=30),
    )
    next_draft = OutreachDraft(
        company_id=company.id,
        channel="email",
        subject="次のご案内",
        body="次の営業メールです。",
    )
    db.add_all((sent, next_draft))
    db.flush()
    queued = EmailDelivery(
        draft_id=next_draft.id,
        company_id=company.id,
        recipient_email=company.email,
        recipient_name=company.company_name,
        subject=next_draft.subject,
        body=next_draft.body,
        scheduled_for=now - timedelta(minutes=1),
        confirmed_at=now - timedelta(minutes=1),
    )
    db.add_all(
        (
            queued,
            SmtpSettings(
                id=1,
                host="smtp.example.com",
                port=587,
                from_email="mailer@example.com",
                timeout_seconds=20,
                max_emails_per_day=1,
                minimum_interval_seconds=60,
            ),
        )
    )
    db.commit()
    assert worker.claim_email_delivery(db) is None

    settings = db.get(SmtpSettings, 1)
    settings.max_emails_per_day = 2
    db.commit()
    assert worker.claim_email_delivery(db) is None

    sent.sent_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    db.commit()
    claimed = worker.claim_email_delivery(db)
    assert claimed is not None and claimed.id == queued.id and claimed.status == "running"
