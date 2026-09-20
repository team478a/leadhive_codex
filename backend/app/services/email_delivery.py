import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import settings


class EmailDeliveryError(Exception):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


def send_email(delivery_id: str, recipient_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise EmailDeliveryError("メール送信設定が未完了です。")
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    message["To"] = recipient_email
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(idstring=delivery_id)
    message.set_content(body)
    try:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as client:
            if settings.smtp_use_starttls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("メール送信に失敗しました。") from exc
