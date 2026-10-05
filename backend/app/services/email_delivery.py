import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.models import SmtpSettings
from app.services.outbound_guard import require_outbound_enabled


class EmailDeliveryError(Exception):
    def __init__(self, public_message: str, unknown: bool = False):
        super().__init__(public_message)
        self.public_message = public_message
        self.unknown = unknown


@dataclass(frozen=True)
class SmtpConfiguration:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_starttls: bool
    timeout_seconds: float


@dataclass(frozen=True)
class EmailDeliveryLimits:
    max_emails_per_day: int
    minimum_interval_seconds: int


def cipher() -> Fernet:
    if not settings.settings_encryption_key:
        raise EmailDeliveryError("設定データ暗号化キーが未設定です。")
    try:
        return Fernet(settings.settings_encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise EmailDeliveryError("設定データ暗号化キーが不正です。") from exc


def encrypt_secret(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise EmailDeliveryError("SMTPパスワードを復号できません。") from exc


def smtp_configuration(db) -> SmtpConfiguration:
    saved = db.get(SmtpSettings, 1)
    if saved:
        return SmtpConfiguration(
            host=saved.host,
            port=saved.port,
            username=saved.username,
            password=decrypt_secret(saved.password_ciphertext) if saved.password_ciphertext else "",
            from_email=saved.from_email,
            from_name=saved.from_name,
            use_starttls=saved.use_starttls,
            timeout_seconds=saved.timeout_seconds,
        )
    return SmtpConfiguration(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_email,
        from_name=settings.smtp_from_name,
        use_starttls=settings.smtp_use_starttls,
        timeout_seconds=settings.smtp_timeout_seconds,
    )


def email_delivery_limits(db) -> EmailDeliveryLimits:
    saved = db.get(SmtpSettings, 1)
    if saved:
        return EmailDeliveryLimits(
            max_emails_per_day=saved.max_emails_per_day,
            minimum_interval_seconds=saved.minimum_interval_seconds,
        )
    return EmailDeliveryLimits(
        max_emails_per_day=settings.smtp_max_emails_per_day,
        minimum_interval_seconds=settings.smtp_minimum_interval_seconds,
    )


def send_with_configuration(
    config: SmtpConfiguration,
    message_id: str,
    recipient_email: str,
    subject: str,
    body: str,
    *,
    stable_message_id: str | None = None,
    unsubscribe_url: str | None = None,
) -> None:
    require_outbound_enabled()
    if not config.host or not config.from_email:
        raise EmailDeliveryError("メール送信設定が未完了です。")
    message = EmailMessage()
    message["From"] = formataddr((config.from_name, config.from_email))
    message["To"] = recipient_email
    message["Subject"] = subject
    message["Message-ID"] = stable_message_id or make_msgid(idstring=message_id)
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(body)
    transmitting = accepted = False
    try:
        with smtplib.SMTP(
            config.host,
            config.port,
            timeout=config.timeout_seconds,
        ) as client:
            if config.use_starttls:
                client.starttls()
            if config.username:
                client.login(config.username, config.password)
            require_outbound_enabled()
            transmitting = True
            client.send_message(message)
            accepted = True
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
        raise EmailDeliveryError("SMTPサーバーがメールを拒否しました。") from exc
    except (OSError, smtplib.SMTPException) as exc:
        if accepted:
            return  # A failed QUIT cannot undo a confirmed SMTP DATA acceptance.
        raise EmailDeliveryError(
            "SMTP受付結果が不明です。再送せず送信履歴を確認してください。"
            if transmitting
            else "メール送信に失敗しました。",
            unknown=transmitting,
        ) from exc


def send_email(db, delivery_id: str, recipient_email: str, subject: str, body: str) -> None:
    require_outbound_enabled()
    send_with_configuration(smtp_configuration(db), delivery_id, recipient_email, subject, body)


def send_test_email(db, recipient_email: str) -> None:
    require_outbound_enabled()
    send_with_configuration(
        smtp_configuration(db),
        "smtp-test",
        recipient_email,
        "LeadHive SMTPテスト送信",
        "LeadHiveのSMTP設定から送信されたテストメールです。",
    )
