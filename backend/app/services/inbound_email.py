import email
import imaplib
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy import func, or_, select

from app.models import (
    Activity,
    Company,
    ContactPerson,
    InboundEmail,
    InboundMailSettings,
    SuppressionEntry,
)
from app.services.email_delivery import EmailDeliveryError, decrypt_secret
from app.services.outreach_attribution import attribute_inbound_reply

logger = logging.getLogger("leadhive")
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
BOUNCE_SUBJECTS = (
    "undelivered",
    "delivery status notification",
    "delivery failure",
    "mail delivery failed",
    "failure notice",
    "配信不能",
    "配信失敗",
    "送信失敗",
    "不達",
)
UNSUBSCRIBE_PHRASES = (
    "配信停止",
    "配信を停止",
    "送信停止",
    "送信を停止",
    "メールを停止",
    "今後の連絡を停止",
    "連絡を停止",
    "unsubscribe",
    "opt out",
    "opt-out",
    "remove me",
)


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
    related_emails: tuple[str, ...] = ()


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


def classify_message(sender_email: str, subject: str, preview: str) -> str:
    text = f"{subject}\n{preview}".lower()
    sender_local = sender_email.partition("@")[0]
    if sender_local in {"mailer-daemon", "postmaster"} or any(
        phrase in text for phrase in BOUNCE_SUBJECTS
    ):
        return "bounce"
    if any(phrase in text for phrase in UNSUBSCRIBE_PHRASES):
        return "unsubscribe"
    return "reply"


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
            related_emails = tuple(
                sorted(
                    {
                        value.lower()
                        for value in EMAIL_PATTERN.findall(raw.decode("utf-8", errors="replace"))
                    }
                )
            )
            messages.append(
                FetchedInboundMessage(
                    uid=uid.decode(),
                    message_id=decode_value(message.get("Message-ID"))[:500],
                    sender_email=sender_email[:320],
                    subject=decode_value(message.get("Subject"))[:500],
                    preview=preview,
                    received_at=received_at(message),
                    related_emails=related_emails,
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


def suppress_company(db, company: Company, reason: str) -> None:
    match = or_(
        (SuppressionEntry.domain != "") & (SuppressionEntry.domain == company.domain),
        (SuppressionEntry.email != "")
        & (func.lower(SuppressionEntry.email) == company.email.lower()),
        (SuppressionEntry.phone != "") & (SuppressionEntry.phone == company.phone),
    )
    entries = db.scalars(
        select(SuppressionEntry).where(SuppressionEntry.project_id == company.project_id, match)
    ).all()
    if entries:
        for entry in entries:
            entry.reason = reason
    else:
        db.add(
            SuppressionEntry(
                project_id=company.project_id,
                domain=company.domain or "",
                email=company.email.lower(),
                phone=company.phone,
                reason=reason,
            )
        )
    company.do_not_contact = True
    company.exclusion_reason = reason
    company.status = "excluded"


def record_inbound_outcome(
    db, company: Company, sender_email: str, subject: str, classification: str, *, manual: bool
) -> None:
    if classification == "bounce":
        reason = "メール不達通知（受信メール）"
        db.add(
            Activity(
                company_id=company.id,
                activity_type="email",
                note=f"{reason}: {sender_email} / 件名: {subject}"[:10000],
            )
        )
        suppress_company(db, company, reason)
        return
    if classification == "unsubscribe":
        reason = "配信停止依頼（受信メール）"
        db.add(
            Activity(
                company_id=company.id,
                activity_type="email",
                note=f"{reason}: {sender_email} / 件名: {subject}"[:10000],
            )
        )
        suppress_company(db, company, reason)
        return
    record_company_reply(db, company, sender_email, subject, manual=manual)


def match_bounce_company(db, related_emails: tuple[str, ...]) -> tuple[Company | None, str]:
    candidates = []
    for email_address in related_emails:
        company, match_type = match_company(db, email_address)
        if company:
            candidates.append((company, match_type))
    unique = {company.id: (company, match_type) for company, match_type in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else (None, "unmatched")


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
            classification = classify_message(
                message.sender_email, message.subject, message.preview
            )
            company, match_type = match_company(db, message.sender_email)
            if classification == "bounce":
                company, match_type = match_bounce_company(db, message.related_emails)
            inbound = InboundEmail(
                mailbox_uid=message.uid,
                message_id=message.message_id,
                sender_email=message.sender_email,
                subject=message.subject,
                preview=message.preview,
                received_at=message.received_at,
                company_id=company.id if company else None,
                match_type=match_type,
                classification=classification,
            )
            db.add(inbound)
            db.flush()
            if company:
                attribute_inbound_reply(db, inbound, company)
                record_inbound_outcome(
                    db,
                    company,
                    message.sender_email,
                    message.subject,
                    classification,
                    manual=False,
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
