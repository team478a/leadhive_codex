from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app import worker
from app.models import (
    Activity,
    Company,
    ContactPerson,
    InboundEmail,
    InboundMailSettings,
    Notification,
    OutreachConversion,
    OutreachDraft,
    OutreachDraftApproval,
    ProjectMember,
    SuppressionEntry,
)
from app.services import email_delivery, inbound_email
from app.services.inbound_email import FetchedInboundMessage


def make_settings(db, monkeypatch):
    monkeypatch.setattr(
        email_delivery.settings,
        "settings_encryption_key",
        Fernet.generate_key().decode(),
    )
    settings = InboundMailSettings(
        id=1,
        host="imap.example.com",
        port=993,
        username="inbox@example.com",
        password_ciphertext=email_delivery.encrypt_secret("imap-password"),
        active=True,
        poll_interval_seconds=60,
        timeout_seconds=15,
    )
    db.add(settings)
    db.commit()
    return settings


def make_company(auth, db, email, status="approached"):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": f"受信メール {email}",
            "target_profile_id": profile_id,
            "sales_objective": "返信確認",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": [f"https://{email.split('@')[1]}"]},
    )
    company = db.get(Company, auth.get(f"/api/projects/{project['id']}/companies").json()[0]["id"])
    company.email = email
    company.status = status
    db.commit()
    return company


def message(uid, sender):
    return FetchedInboundMessage(
        uid=uid,
        message_id=f"<{uid}@example.com>",
        sender_email=sender,
        subject="ご連絡ありがとうございます",
        preview="詳しくお話を伺えますでしょうか。",
        received_at=datetime.now(timezone.utc),
    )


def test_inbound_sync_matches_company_updates_reply_and_is_idempotent(auth, db, monkeypatch):
    make_settings(db, monkeypatch)
    company = make_company(auth, db, "contact@reply.example")
    marked = []
    monkeypatch.setattr(
        inbound_email,
        "fetch_unseen_messages",
        lambda _config: ([message("100", company.email)], ["100"]),
    )
    monkeypatch.setattr(
        inbound_email, "mark_messages_seen", lambda _config, uids: marked.extend(uids)
    )

    assert inbound_email.sync_inbound_mail(db, force=True) == 1
    db.refresh(company)
    assert company.status == "replied"
    saved = db.scalar(select(InboundEmail).where(InboundEmail.mailbox_uid == "100"))
    assert saved and saved.company_id == company.id and saved.match_type == "company_email"
    notes = db.scalars(select(Activity.note).where(Activity.company_id == company.id)).all()
    assert any("受信メール" in note for note in notes)
    assert any("返信あり（受信メール）" in note for note in notes)
    assert marked == ["100"]

    assert inbound_email.sync_inbound_mail(db, force=True) == 0
    assert db.scalar(select(InboundEmail).where(InboundEmail.mailbox_uid == "100"))


def test_inbound_reply_notifies_project_owner_and_editors(auth, users, db, monkeypatch):
    make_settings(db, monkeypatch)
    company = make_company(auth, db, "contact@reply-notification.example")
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="editor"))
    db.commit()
    received = message("reply-notification-100", company.email)
    monkeypatch.setattr(
        inbound_email,
        "fetch_unseen_messages",
        lambda _config: ([received], [received.uid]),
    )
    monkeypatch.setattr(inbound_email, "mark_messages_seen", lambda *_args: None)

    assert inbound_email.sync_inbound_mail(db, force=True) == 1
    notifications = db.scalars(
        select(Notification).where(Notification.notification_type == "inbound_reply_received")
    ).all()
    assert {item.user_id for item in notifications} == {users[0].id, users[1].id}
    assert all(item.company_id == company.id for item in notifications)
    assert all(item.inbound_email_id is not None for item in notifications)
    assert all(received.subject in item.message for item in notifications)
    notification_response = auth.get("/api/notifications").json()
    assert next(
        item
        for item in notification_response
        if item["notification_type"] == "inbound_reply_received"
    )["inbound_email_id"] == str(notifications[0].inbound_email_id)
    assert inbound_email.sync_inbound_mail(db, force=True) == 0
    assert db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.notification_type == "inbound_reply_received")
    ) == 2


def test_inbound_sync_matches_contact_and_preserves_later_sales_status(auth, db, monkeypatch):
    make_settings(db, monkeypatch)
    company = make_company(auth, db, "main@meeting.example", status="meeting")
    db.add(ContactPerson(company_id=company.id, name="山田", email="yamada@meeting.example"))
    db.commit()
    monkeypatch.setattr(
        inbound_email,
        "fetch_unseen_messages",
        lambda _config: ([message("101", "yamada@meeting.example")], ["101"]),
    )
    monkeypatch.setattr(inbound_email, "mark_messages_seen", lambda *_args: None)

    assert inbound_email.sync_inbound_mail(db, force=True) == 1
    db.refresh(company)
    assert company.status == "meeting"
    saved = db.scalar(select(InboundEmail).where(InboundEmail.mailbox_uid == "101"))
    assert saved and saved.company_id == company.id and saved.match_type == "contact_person"
    assert not any(
        "返信あり（受信メール）" in note
        for note in db.scalars(select(Activity.note).where(Activity.company_id == company.id)).all()
    )


def test_inbound_reply_attributes_to_the_latest_eligible_approval(auth, db, monkeypatch):
    make_settings(db, monkeypatch)
    company = make_company(auth, db, "contact@attribution.example")
    older = OutreachDraft(
        company_id=company.id,
        channel="email",
        subject="以前のご案内",
        body="以前のご案内です。",
    )
    latest = OutreachDraft(
        company_id=company.id,
        channel="email",
        subject="最新のご案内",
        body="最新のご案内です。",
    )
    queued = OutreachDraft(
        company_id=company.id,
        channel="email",
        subject="未送信のご案内",
        body="まだ送信していないご案内です。",
    )
    db.add_all((older, latest, queued))
    db.flush()
    now = datetime.now(timezone.utc)
    db.add_all(
        (
            OutreachDraftApproval(
                draft_id=older.id,
                approval_type="email",
                subject=older.subject,
                body=older.body,
                approved_at=now - timedelta(days=2),
                delivered_at=now - timedelta(days=2),
            ),
            OutreachDraftApproval(
                draft_id=latest.id,
                approval_type="email",
                subject=latest.subject,
                body=latest.body,
                approved_at=now - timedelta(days=1),
                delivered_at=now - timedelta(days=1),
            ),
            OutreachDraftApproval(
                draft_id=queued.id,
                approval_type="email",
                subject=queued.subject,
                body=queued.body,
                approved_at=now,
            ),
        )
    )
    db.commit()
    latest_approval = db.scalar(
        select(OutreachDraftApproval).where(OutreachDraftApproval.draft_id == latest.id)
    )
    received = message("attribution-100", company.email)
    monkeypatch.setattr(
        inbound_email,
        "fetch_unseen_messages",
        lambda _config: ([received], [received.uid]),
    )
    monkeypatch.setattr(inbound_email, "mark_messages_seen", lambda *_args: None)

    assert inbound_email.sync_inbound_mail(db, force=True) == 1
    inbound = db.scalar(select(InboundEmail).where(InboundEmail.mailbox_uid == received.uid))
    assert inbound.outreach_approval_id == latest_approval.id
    assert db.scalar(
        select(OutreachConversion).where(
            OutreachConversion.approval_id == latest_approval.id,
            OutreachConversion.outcome == "replied",
        )
    )


def test_inbound_reply_does_not_attribute_an_unsent_approval(auth, db, monkeypatch):
    make_settings(db, monkeypatch)
    company = make_company(auth, db, "contact@unsent-attribution.example")
    draft = OutreachDraft(
        company_id=company.id,
        channel="email",
        subject="未送信のご案内",
        body="まだ送信していないご案内です。",
    )
    db.add(draft)
    db.flush()
    db.add(
        OutreachDraftApproval(
            draft_id=draft.id,
            approval_type="email",
            subject=draft.subject,
            body=draft.body,
        )
    )
    db.commit()
    received = message("unsent-attribution-100", company.email)
    monkeypatch.setattr(
        inbound_email,
        "fetch_unseen_messages",
        lambda _config: ([received], [received.uid]),
    )
    monkeypatch.setattr(inbound_email, "mark_messages_seen", lambda *_args: None)

    assert inbound_email.sync_inbound_mail(db, force=True) == 1
    inbound = db.scalar(select(InboundEmail).where(InboundEmail.mailbox_uid == received.uid))
    assert inbound.outreach_approval_id is None
    assert not db.scalar(
        select(OutreachConversion).where(OutreachConversion.company_id == company.id)
    )


def test_worker_runs_inbound_sync_before_other_work(db, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "sync_inbound_mail", lambda _db: calls.append(True) or 1)
    assert worker.run_once() is True
    assert calls == [True]


def test_inbound_unsubscribe_and_bounce_suppress_matched_companies(auth, db, monkeypatch):
    make_settings(db, monkeypatch)
    unsubscribe_company = make_company(auth, db, "contact@unsubscribe.example")
    bounce_company = make_company(auth, db, "contact@bounce.example")
    unsubscribe = FetchedInboundMessage(
        uid="unsubscribe-100",
        message_id="<unsubscribe-100@example.com>",
        sender_email=unsubscribe_company.email,
        subject="今後の連絡を停止してください",
        preview="配信停止をお願いします。",
        received_at=datetime.now(timezone.utc),
    )
    bounce = FetchedInboundMessage(
        uid="bounce-100",
        message_id="<bounce-100@example.com>",
        sender_email="mailer-daemon@example.net",
        subject="Undelivered Mail Returned to Sender",
        preview="Delivery failed for contact@bounce.example",
        received_at=datetime.now(timezone.utc),
        related_emails=("contact@bounce.example",),
    )
    monkeypatch.setattr(
        inbound_email,
        "fetch_unseen_messages",
        lambda _config: ([unsubscribe, bounce], [unsubscribe.uid, bounce.uid]),
    )
    monkeypatch.setattr(inbound_email, "mark_messages_seen", lambda *_args: None)

    assert inbound_email.sync_inbound_mail(db, force=True) == 2
    db.refresh(unsubscribe_company)
    db.refresh(bounce_company)
    assert unsubscribe_company.do_not_contact and unsubscribe_company.status == "excluded"
    assert bounce_company.do_not_contact and bounce_company.status == "excluded"
    classifications = dict(
        db.execute(select(InboundEmail.mailbox_uid, InboundEmail.classification)).all()
    )
    assert classifications == {"unsubscribe-100": "unsubscribe", "bounce-100": "bounce"}
    reasons = db.scalars(select(SuppressionEntry.reason)).all()
    assert "配信停止依頼（受信メール）" in reasons
    assert "メール不達通知（受信メール）" in reasons


def test_admin_can_search_and_manually_match_unmatched_inbound_email(auth, users, db):
    users[0].is_admin = True
    db.commit()
    company = make_company(auth, db, "contact@manual.example")
    inbound = InboundEmail(
        mailbox_uid="manual-100",
        sender_email="shared@manual.example",
        subject="日程について",
        preview="来週でしたら対応可能です。",
        received_at=datetime.now(timezone.utc),
        match_type="unmatched",
    )
    db.add(inbound)
    db.commit()

    candidates = auth.get(
        "/api/admin/inbound-email-companies", params={"query": company.company_name}
    )
    assert candidates.status_code == 200
    assert candidates.json()[0]["id"] == str(company.id)

    matched = auth.post(
        f"/api/admin/inbound-emails/{inbound.id}/match", json={"company_id": str(company.id)}
    )
    assert matched.status_code == 200
    assert matched.json()["company_name"] == company.company_name
    assert matched.json()["match_type"] == "manual"
    db.refresh(company)
    assert company.status == "replied"
    notes = db.scalars(select(Activity.note).where(Activity.company_id == company.id)).all()
    assert any("受信メールを手動紐付け" in note for note in notes)
    assert db.scalar(
        select(Notification).where(
            Notification.company_id == company.id,
            Notification.notification_type == "inbound_reply_received",
        )
    )
    assert (
        auth.post(
            f"/api/admin/inbound-emails/{inbound.id}/match", json={"company_id": str(company.id)}
        ).status_code
        == 409
    )


def test_reply_queue_lists_received_replies_and_records_response(auth, db, monkeypatch):
    make_settings(db, monkeypatch)
    company = make_company(auth, db, "contact@queue.example")
    draft = OutreachDraft(
        company_id=company.id,
        channel="email",
        subject="商談のご相談",
        body="短時間の情報交換をご相談させてください。",
    )
    db.add(draft)
    db.flush()
    approval = OutreachDraftApproval(
        draft_id=draft.id,
        approval_type="email",
        subject=draft.subject,
        body=draft.body,
        delivered_at=datetime.now(timezone.utc),
    )
    db.add(approval)
    db.commit()
    received = message("queue-100", company.email)
    monkeypatch.setattr(
        inbound_email,
        "fetch_unseen_messages",
        lambda _config: ([received], [received.uid]),
    )
    monkeypatch.setattr(inbound_email, "mark_messages_seen", lambda *_args: None)
    assert inbound_email.sync_inbound_mail(db, force=True) == 1

    queue = auth.get(f"/api/projects/{company.project_id}/reply-queue")
    assert queue.status_code == 200
    assert queue.json()[0]["company"]["id"] == str(company.id)
    assert queue.json()[0]["subject"] == received.subject
    inbound_email_id = queue.json()[0]["inbound_email_id"]
    inbound = db.get(InboundEmail, inbound_email_id)
    assert inbound.outreach_approval_id == approval.id
    assert db.scalar(
        select(OutreachConversion).where(
            OutreachConversion.approval_id == approval.id,
            OutreachConversion.outcome == "replied",
        )
    )
    response = auth.post(
        f"/api/companies/{company.id}/reply-response",
        json={
            "inbound_email_id": inbound_email_id,
            "outcome": "meeting",
            "note": "オンライン商談の日程を確定",
            "next_followup_at": None,
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "meeting"
    assert auth.get(f"/api/projects/{company.project_id}/reply-queue").json() == []
    db.refresh(inbound)
    assert inbound.handled_at is not None
    notes = db.scalars(select(Activity.note).where(Activity.company_id == company.id)).all()
    assert "オンライン商談の日程を確定" in notes
    assert db.scalar(
        select(OutreachConversion).where(
            OutreachConversion.approval_id == approval.id,
            OutreachConversion.outcome == "meeting",
        )
    )


def test_reply_response_marks_continued_reply_handled_and_keeps_new_replies(auth, db):
    company = make_company(auth, db, "contact@handled-reply.example", status="replied")
    inbound = InboundEmail(
        mailbox_uid="handled-reply-100",
        sender_email=company.email,
        subject="ご相談について",
        preview="来週に詳しくお話しできればと思います。",
        received_at=datetime.now(timezone.utc),
        company_id=company.id,
        match_type="company_email",
    )
    db.add(inbound)
    db.commit()

    response = auth.post(
        f"/api/companies/{company.id}/reply-response",
        json={
            "inbound_email_id": str(inbound.id),
            "outcome": "replied",
            "note": "確認済み。次回の連絡日時を設定。",
            "next_followup_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "replied"
    db.refresh(inbound)
    assert inbound.handled_at is not None
    assert auth.get(f"/api/projects/{company.project_id}/reply-queue").json() == []

    later = InboundEmail(
        mailbox_uid="handled-reply-101",
        sender_email=company.email,
        subject="追加のご質問",
        preview="確認したい点があります。",
        received_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        company_id=company.id,
        match_type="company_email",
    )
    db.add(later)
    db.commit()
    queue = auth.get(f"/api/projects/{company.project_id}/reply-queue").json()
    assert len(queue) == 1 and queue[0]["inbound_email_id"] == str(later.id)
