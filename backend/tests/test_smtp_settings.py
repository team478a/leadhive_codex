from cryptography.fernet import Fernet

from app import admin_routes
from app.models import ApplicationSettings, InboundMailSettings, SmtpSettings
from app.services import application_settings, email_delivery


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


def test_admin_can_store_application_settings_without_exposing_api_keys(
    auth, users, db, monkeypatch
):
    users[0].is_admin = True
    db.commit()
    monkeypatch.setattr(
        email_delivery.settings, "settings_encryption_key", Fernet.generate_key().decode()
    )
    for field in (
        "public_app_url",
        "openai_api_key",
        "openai_model",
        "serper_api_key",
        "google_places_api_key",
        "gbizinfo_api_token",
        "gbizinfo_api_base_url",
    ):
        monkeypatch.setattr(application_settings.settings, field, "")
    saved = auth.put(
        "/api/admin/application-settings",
        json={
            "public_app_url": "https://app.example.com",
            "openai_model": "gpt-5.6-luna",
            "openai_api_key": "test-openai-key",
            "serper_api_key": "test-serper-key",
            "google_places_api_key": "test-places-key",
            "gbizinfo_api_token": "test-gbizinfo-token",
            "gbizinfo_api_base_url": "https://api.example.com/corporations",
        },
    )
    assert saved.status_code == 200
    result = saved.json()
    assert result["settings_encryption_ready"] is True
    assert result["openai_api_key_source"] == "database"
    assert result["serper_api_key_source"] == "database"
    assert "openai_api_key" not in result
    row = db.get(ApplicationSettings, 1)
    assert row.openai_api_key_ciphertext != "test-openai-key"
    assert email_delivery.decrypt_secret(row.openai_api_key_ciphertext) == "test-openai-key"
    assert application_settings.settings.openai_api_key == "test-openai-key"
    assert application_settings.settings.public_app_url == "https://app.example.com"


def test_application_settings_require_admin(auth):
    assert auth.get("/api/admin/application-settings").status_code == 404
    assert auth.post("/api/admin/application-settings/test/serper").status_code == 404


def test_admin_can_run_service_connection_test(auth, users, db, monkeypatch):
    users[0].is_admin = True
    db.commit()
    calls = []

    def test_connection(service):
        calls.append(service)
        return True, "Serper APIへ正常に接続できました。"

    monkeypatch.setattr(admin_routes, "test_service_connection", test_connection)
    response = auth.post("/api/admin/application-settings/test/serper")
    assert response.status_code == 200
    assert response.json()["service"] == "serper"
    assert response.json()["ok"] is True
    assert calls == ["serper"]
