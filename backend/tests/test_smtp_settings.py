from cryptography.fernet import Fernet

from app import admin_routes
from app.models import InboundMailSettings, SmtpSettings
from app.services import email_delivery


def smtp_body(password="smtp-password"):
    return {
        "host": "smtp.example.com",
        "port": 587,
        "username": "mailer@example.com",
        "password": password,
        "from_email": "mailer@example.com",
        "from_name": "LeadHive Test",
        "use_starttls": True,
        "timeout_seconds": 15,
        "max_emails_per_day": 80,
        "minimum_interval_seconds": 45,
    }


def inbound_body(password="imap-password"):
    return {
        "host": "imap.example.com",
        "port": 993,
        "username": "inbox@example.com",
        "password": password,
        "mailbox": "INBOX",
        "use_ssl": True,
        "timeout_seconds": 15,
        "poll_interval_seconds": 300,
        "active": True,
    }


def test_admin_can_store_encrypted_smtp_settings_and_send_test(auth, users, db, monkeypatch):
    users[0].is_admin = True
    db.commit()
    monkeypatch.setattr(
        email_delivery.settings,
        "settings_encryption_key",
        Fernet.generate_key().decode(),
    )
    assert auth.get("/api/admin/smtp-settings").json() is None
    saved = auth.put("/api/admin/smtp-settings", json=smtp_body())
    assert saved.status_code == 200
    result = saved.json()
    assert result["password_configured"] is True
    assert result["max_emails_per_day"] == 80
    assert result["minimum_interval_seconds"] == 45
    assert "password" not in result
    row = db.get(SmtpSettings, 1)
    assert row.password_ciphertext != "smtp-password"
    assert email_delivery.decrypt_secret(row.password_ciphertext) == "smtp-password"

    calls = []
    monkeypatch.setattr(
        admin_routes,
        "send_test_email",
        lambda _db, recipient: calls.append(recipient),
    )
    assert (
        auth.post(
            "/api/admin/smtp-settings/test",
            json={"recipient_email": "owner@example.com"},
        ).status_code
        == 204
    )
    assert calls == ["owner@example.com"]

    updated = auth.put("/api/admin/smtp-settings", json=smtp_body(password=None))
    assert updated.status_code == 200 and updated.json()["password_configured"] is True
    assert (
        email_delivery.decrypt_secret(db.get(SmtpSettings, 1).password_ciphertext)
        == "smtp-password"
    )


def test_smtp_settings_require_admin_and_encryption_key(auth, users, db, monkeypatch):
    assert auth.get("/api/admin/smtp-settings").status_code == 404
    users[0].is_admin = True
    db.commit()
    monkeypatch.setattr(email_delivery.settings, "settings_encryption_key", "")
    blocked = auth.put("/api/admin/smtp-settings", json=smtp_body())
    assert blocked.status_code == 503
    assert blocked.json()["detail"] == "設定データ暗号化キーが未設定です。"


def test_admin_can_store_and_test_encrypted_inbound_mail_settings(auth, users, db, monkeypatch):
    users[0].is_admin = True
    db.commit()
    monkeypatch.setattr(
        email_delivery.settings,
        "settings_encryption_key",
        Fernet.generate_key().decode(),
    )
    saved = auth.put("/api/admin/inbound-mail-settings", json=inbound_body())
    assert saved.status_code == 200
    assert saved.json()["password_configured"] is True
    assert "password" not in saved.json()
    row = db.get(InboundMailSettings, 1)
    assert row.password_ciphertext != "imap-password"
    assert email_delivery.decrypt_secret(row.password_ciphertext) == "imap-password"

    calls = []

    class Mailbox:
        def logout(self):
            calls.append("logout")

    monkeypatch.setattr(admin_routes, "open_mailbox", lambda _config: Mailbox())
    assert auth.post("/api/admin/inbound-mail-settings/test").status_code == 204
    assert calls == ["logout"]

    updated = auth.put("/api/admin/inbound-mail-settings", json=inbound_body(password=None))
    assert updated.status_code == 200 and updated.json()["password_configured"] is True
