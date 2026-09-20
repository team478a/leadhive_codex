from cryptography.fernet import Fernet

from app import admin_routes
from app.models import SmtpSettings
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
