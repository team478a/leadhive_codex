import smtplib
import ssl
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services import smtp_connection
from app.services.email_delivery import EmailDeliveryError, SmtpConfiguration


@pytest.fixture
def smtp(monkeypatch):
    config = SmtpConfiguration(
        "smtp.example.com", 587, "user", "secret", "sender@example.com", "Sender", True, 120
    )
    monkeypatch.setattr(smtp_connection, "smtp_configuration", lambda db: config)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    transport = MagicMock()
    client = transport.return_value.__enter__.return_value
    client.ehlo.return_value = (250, b"ok")
    monkeypatch.setattr(smtp_connection.smtplib, "SMTP", transport)
    yield config, transport, client
    for method in ("send_message", "sendmail", "mail", "rcpt", "data"):
        getattr(client, method).assert_not_called()


def test_tls_and_auth_without_delivery_when_outbound_off(smtp):
    _, transport, client = smtp
    result = smtp_connection.check_smtp_connection(None)
    assert result.ok and result.authenticated and result.tls_verified
    transport.assert_called_once_with("smtp.example.com", 587, timeout=15)
    context = client.starttls.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert client.ehlo.call_count == 2
    client.login.assert_called_once_with("user", "secret")


@pytest.mark.parametrize(
    "changes",
    [
        {"host": ""},
        {"port": 465},
        {"use_starttls": False},
        {"password": ""},
    ],
)
def test_unsafe_or_missing_configuration_does_not_connect(smtp, monkeypatch, changes):
    config, transport, _ = smtp
    monkeypatch.setattr(
        smtp_connection, "smtp_configuration", lambda db: replace(config, **changes)
    )
    result = smtp_connection.check_smtp_connection(None)
    assert not result.ok and result.stage == "configuration"
    transport.assert_not_called()


@pytest.mark.parametrize(
    "method,error,stage",
    [
        ("connect", OSError("secret"), "connection"),
        ("starttls", ssl.SSLCertVerificationError("secret"), "tls"),
        ("login", smtplib.SMTPAuthenticationError(535, b"secret"), "authentication"),
    ],
)
def test_errors_are_sanitized_and_tls_failure_never_authenticates(smtp, method, error, stage):
    _, transport, client = smtp
    if method == "connect":
        transport.side_effect = error
    else:
        getattr(client, method).side_effect = error
    result = smtp_connection.check_smtp_connection(None)
    assert not result.ok and result.stage == stage
    assert "secret" not in result.model_dump_json()
    if method != "login":
        client.login.assert_not_called()


def test_no_authentication_is_reported_honestly(smtp, monkeypatch):
    config, _, client = smtp
    monkeypatch.setattr(
        smtp_connection, "smtp_configuration", lambda db: replace(config, username="")
    )
    result = smtp_connection.check_smtp_connection(None)
    assert result.ok and not result.authenticated and "未実施" in result.message
    client.login.assert_not_called()


def test_decryption_failure_is_sanitized(smtp, monkeypatch):
    _, transport, _ = smtp

    def fail(db):
        raise EmailDeliveryError("secret")

    monkeypatch.setattr(smtp_connection, "smtp_configuration", fail)
    result = smtp_connection.check_smtp_connection(None)
    assert not result.ok and "secret" not in result.model_dump_json()
    transport.assert_not_called()


def test_non_admin_and_unauthenticated_cannot_connect(client, auth, users, db, smtp):
    _, transport, _ = smtp
    assert auth.post("/api/admin/smtp-settings/connection-test").status_code == 404
    auth.post("/api/auth/logout")
    assert client.post("/api/admin/smtp-settings/connection-test").status_code == 401
    transport.assert_not_called()


def test_admin_endpoint_with_outbound_off_cannot_send(auth, users, db, smtp):
    users[0].is_admin = True
    db.commit()
    response = auth.post("/api/admin/smtp-settings/connection-test", json={"confirmed": True})
    assert response.status_code == 200 and response.json()["ok"]
    assert response.json()["stage"] == "completed"
    assert "secret" not in response.text
