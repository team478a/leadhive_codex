import email
import imaplib
import logging
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy import func, select

from app.models import Activity, Company, ContactPerson, InboundEmail, InboundMailSettings
from app.services.email_delivery import EmailDeliveryError, decrypt_secret

logger = logging.getLogger("leadhive")


class InboundMailError(Exception):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


@dataclass(frozen=True)
class InboundMailConfiguration:
    host: str
    port: int
    username: str
    password: str
    mailbox: str
    use_ssl: bool
    timeout_seconds: float


@dataclass(frozen=True)
class FetchedInboundMessage:
    uid: str
    message_id: str
    sender_email: str
    subject: str
    preview: str
    received_at: datetime


def decode_value(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for fragment, encoding in decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts).strip()


def inbound_configuration(saved: InboundMailSettings) -> InboundMailConfiguration:
    try:
        password = decrypt_secret(saved.password_ciphertext) if saved.password_ciphertext else ""
    except EmailDeliveryError as exc:
        raise InboundMailError("受信メールのパスワードを復号できません。") from exc
    if not saved.host or not saved.username or not password:
        raise InboundMailError("受信メール設定が未完了です。")
    return InboundMailConfiguration(
        host=saved.host,
        port=saved.port,
        username=saved.username,
        password=password,
        mailbox=saved.mailbox,
        use_ssl=saved.use_ssl,
        timeout_seconds=saved.timeout_seconds,
    )


def open_mailbox(config: InboundMailConfiguration):
    try:
        if config.use_ssl:
            client = imaplib.IMAP4_SSL(
                config.host,
                config.port,
                ssl_context=ssl.create_default_context(),
                timeout=config.timeout_seconds,
            )
        else:
            client = imaplib.IMAP4(config.host, config.port, timeout=config.timeout_seconds)
        client.login(config.username, config.password)
        status, _ = client.select(config.mailbox)
        if status != "OK":
            raise InboundMailError("受信メールのフォルダーを開けません。")
        return client
    except InboundMailError:
        raise
    except (OSError, imaplib.IMAP4.error) as exc:
        raise InboundMailError("受信メールサーバーへ接続できません。") from exc


def received_at(message: email.message.Message) -> datetime:
    try:
        value = parsedate_to_datetime(message.get("Date"))
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return datetime.now(timezone.utc)


def fetch_unseen_messages(
    config: InboundMailConfiguration, limit: int = 50
) -> tuple[list[FetchedInboundMessage], list[str]]:
    client = open_mailbox(config)
    try:
        status, data = client.uid("search", None, "UNSEEN")
        if status != "OK":
            raise InboundMailError("未読メールを確認できません。")
        uids = data[0].split()[-limit:]
        messages = []
        for uid in uids:
            status, data = client.uid("fetch", uid, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.4096>)")
            if status != "OK":
                continue
            raw = b"".join(
                item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)
            )
            message = email.message_from_bytes(raw)
            sender_email = parseaddr(message.get("From", ""))[1].strip().lower()
            if not sender_email:
                continue
            preview = " ".join(
                raw.split(b"\r\n\r\n", 1)[-1].decode("utf-8", errors="replace").split()
            )[:1000]
            messages.append(
                FetchedInboundMessage(
                    uid=uid.decode(),
                    message_id=decode_value(message.get("Message-ID"))[:500],
                    sender_email=sender_email[:320],
                    subject=decode_value(message.get("Subject"))[:500],
                    preview=preview,
                    received_at=received_at(message),
                )
            )
        return messages, [uid.decode() for uid in uids]
    finally:
        try:
            client.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def mark_messages_seen(config: InboundMailConfiguration, uids: list[str]) -> None:
    if not uids:
        return
    client = open_mailbox(config)
    try:
        for uid in uids:
            client.uid("store", uid, "+FLAGS.SILENT", "(\\Seen)")
    finally:
        try:
            client.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def match_company(db, sender_email: str) -> tuple[Company | None, str]:
    direct_ids = set(
        db.scalars(select(Company.id).where(func.lower(Company.email) == sender_email)).all()
    )
    contact_ids = set(
        db.scalars(
            select(ContactPerson.company_id).where(func.lower(ContactPerson.email) == sender_email)
        ).all()
    )
    candidates = direct_ids | contact_ids
    if len(candidates) != 1:
        return None, "unmatched"
    company = db.get(Company, next(iter(candidates)))
    if company is None:
        return None, "unmatched"
    return company, "company_email" if company.id in direct_ids else "contact_person"


def record_company_reply(
    db, company: Company, sender_email: str, subject: str, *, manual: bool
) -> None:
    prefix = "受信メールを手動紐付け" if manual else "受信メール"
    db.add(
        Activity(
            company_id=company.id,
            activity_type="email",
            note=f"{prefix}: {sender_email} / 件名: {subject}"[:10000],
        )
    )
    if company.status in {"unreviewed", "target", "approached"}:
        company.status = "replied"
        db.add(
            Activity(
                company_id=company.id,
                activity_type="status_change",
                note="営業状況を更新: 返信あり（受信メール）",
            )
        )


def sync_inbound_mail(db, force: bool = False, raise_on_error: bool = False) -> int:
    saved = db.get(InboundMailSettings, 1)
    if saved is None or not saved.active:
        return 0
    now = datetime.now(timezone.utc)
    if (
        not force
        and saved.last_polled_at
        and saved.last_polled_at > now - timedelta(seconds=saved.poll_interval_seconds)
    ):
        return 0
    try:
        config = inbound_configuration(saved)
        messages, uids = fetch_unseen_messages(config)
        processed = 0
        for message in messages:
            if db.scalar(select(InboundEmail.id).where(InboundEmail.mailbox_uid == message.uid)):
                continue
            company, match_type = match_company(db, message.sender_email)
            inbound = InboundEmail(
                mailbox_uid=message.uid,
                message_id=message.message_id,
                sender_email=message.sender_email,
                subject=message.subject,
                preview=message.preview,
                received_at=message.received_at,
                company_id=company.id if company else None,
                match_type=match_type,
            )
            db.add(inbound)
            if company:
                record_company_reply(
                    db, company, message.sender_email, message.subject, manual=False
                )
            processed += 1
        saved.last_polled_at = now
        saved.last_error = ""
        db.commit()
        mark_messages_seen(config, uids)
        logger.info("inbound email sync: processed=%s", processed)
        return processed
    except InboundMailError as exc:
        db.rollback()
        saved = db.get(InboundMailSettings, 1)
        if saved:
            saved.last_polled_at = now
            saved.last_error = exc.public_message[:500]
            db.commit()
        logger.warning("inbound email sync failed: type=%s", type(exc).__name__)
        if raise_on_error:
            raise
        return 0
