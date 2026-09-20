from contextlib import nullcontext

from sqlalchemy import select

from app import worker
from app.models import Activity, Company, OutreachDraft
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
    draft.subject = "送信後に編集した件名"
    db.commit()
    sent = []
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "send_email", lambda *args: sent.append(args))
    assert worker.run_once()
    result = auth.get(f"/api/outreach-drafts/{draft.id}/email-delivery").json()
    assert result["status"] == "sent" and result["sent_at"]
    assert sent[0][1] == company.email and sent[0][2] == "サービスのご相談"
    activity = db.scalar(
        select(Activity).where(Activity.company_id == company.id, Activity.activity_type == "email")
    )
    assert activity is not None
    assert "メール送信" in activity.note
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
