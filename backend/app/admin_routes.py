import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, InboundEmail, InboundMailSettings, SmtpSettings, User
from app.schemas import (
    InboundEmailOut,
    InboundMailSettingsInput,
    InboundMailSettingsOut,
    InboundMailSyncOut,
    SmtpSettingsInput,
    SmtpSettingsOut,
    SmtpTestInput,
)
from app.security import current_admin
from app.services.email_delivery import EmailDeliveryError, encrypt_secret, send_test_email
from app.services.inbound_email import (
    InboundMailError,
    inbound_configuration,
    open_mailbox,
    sync_inbound_mail,
)

logger = logging.getLogger("leadhive")
router = APIRouter(prefix="/api/admin")


def smtp_out(value: SmtpSettings) -> SmtpSettingsOut:
    return SmtpSettingsOut(
        host=value.host,
        port=value.port,
        username=value.username,
        from_email=value.from_email,
        from_name=value.from_name,
        use_starttls=value.use_starttls,
        timeout_seconds=value.timeout_seconds,
        max_emails_per_day=value.max_emails_per_day,
        minimum_interval_seconds=value.minimum_interval_seconds,
        password_configured=bool(value.password_ciphertext),
        updated_at=value.updated_at,
    )


def inbound_mail_out(value: InboundMailSettings) -> InboundMailSettingsOut:
    return InboundMailSettingsOut(
        host=value.host,
        port=value.port,
        username=value.username,
        mailbox=value.mailbox,
        use_ssl=value.use_ssl,
        timeout_seconds=value.timeout_seconds,
        poll_interval_seconds=value.poll_interval_seconds,
        active=value.active,
        password_configured=bool(value.password_ciphertext),
        last_polled_at=value.last_polled_at,
        last_error=value.last_error,
        updated_at=value.updated_at,
    )


@router.get("/smtp-settings", response_model=SmtpSettingsOut | None)
def get_smtp_settings(db: Session = Depends(get_db), user: User = Depends(current_admin)):
    saved = db.get(SmtpSettings, 1)
    return smtp_out(saved) if saved else None


@router.put("/smtp-settings", response_model=SmtpSettingsOut)
def update_smtp_settings(
    body: SmtpSettingsInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    saved = db.get(SmtpSettings, 1)
    try:
        password_ciphertext = encrypt_secret(body.password) if body.password is not None else None
    except EmailDeliveryError as exc:
        raise HTTPException(503, exc.public_message) from exc
    existing_password = saved.password_ciphertext if saved else ""
    if body.username and not (password_ciphertext or existing_password):
        raise HTTPException(422, "ユーザー名を指定する場合はSMTPパスワードを入力してください。")
    if saved is None:
        saved = SmtpSettings(
            id=1,
            host=body.host,
            port=body.port,
            username=body.username,
            password_ciphertext=password_ciphertext or "",
            from_email=str(body.from_email),
            from_name=body.from_name,
            use_starttls=body.use_starttls,
            timeout_seconds=body.timeout_seconds,
            max_emails_per_day=body.max_emails_per_day,
            minimum_interval_seconds=body.minimum_interval_seconds,
            updated_by_user_id=user.id,
        )
        db.add(saved)
    else:
        saved.host = body.host
        saved.port = body.port
        saved.username = body.username
        saved.from_email = str(body.from_email)
        saved.from_name = body.from_name
        saved.use_starttls = body.use_starttls
        saved.timeout_seconds = body.timeout_seconds
        saved.max_emails_per_day = body.max_emails_per_day
        saved.minimum_interval_seconds = body.minimum_interval_seconds
        saved.updated_by_user_id = user.id
        if password_ciphertext is not None:
            saved.password_ciphertext = password_ciphertext
    db.commit()
    db.refresh(saved)
    logger.info("SMTP settings updated: user_id=%s", user.id)
    return smtp_out(saved)


@router.post("/smtp-settings/test", status_code=204)
def test_smtp_settings(
    body: SmtpTestInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    try:
        send_test_email(db, str(body.recipient_email))
    except EmailDeliveryError as exc:
        logger.warning("SMTP test failed: type=%s", type(exc).__name__)
        raise HTTPException(503, exc.public_message) from exc
    logger.info("SMTP test sent: user_id=%s", user.id)


@router.get("/inbound-mail-settings", response_model=InboundMailSettingsOut | None)
def get_inbound_mail_settings(db: Session = Depends(get_db), user: User = Depends(current_admin)):
    saved = db.get(InboundMailSettings, 1)
    return inbound_mail_out(saved) if saved else None


@router.put("/inbound-mail-settings", response_model=InboundMailSettingsOut)
def update_inbound_mail_settings(
    body: InboundMailSettingsInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    saved = db.get(InboundMailSettings, 1)
    try:
        password_ciphertext = encrypt_secret(body.password) if body.password is not None else None
    except EmailDeliveryError as exc:
        raise HTTPException(503, exc.public_message) from exc
    existing_password = saved.password_ciphertext if saved else ""
    if not (password_ciphertext or existing_password):
        raise HTTPException(422, "受信メールのパスワードを入力してください。")
    if saved is None:
        saved = InboundMailSettings(
            id=1,
            host=body.host,
            port=body.port,
            username=str(body.username),
            password_ciphertext=password_ciphertext or "",
            mailbox=body.mailbox,
            use_ssl=body.use_ssl,
            timeout_seconds=body.timeout_seconds,
            poll_interval_seconds=body.poll_interval_seconds,
            active=body.active,
            updated_by_user_id=user.id,
        )
        db.add(saved)
    else:
        saved.host = body.host
        saved.port = body.port
        saved.username = str(body.username)
        saved.mailbox = body.mailbox
        saved.use_ssl = body.use_ssl
        saved.timeout_seconds = body.timeout_seconds
        saved.poll_interval_seconds = body.poll_interval_seconds
        saved.active = body.active
        saved.updated_by_user_id = user.id
        if password_ciphertext is not None:
            saved.password_ciphertext = password_ciphertext
    db.commit()
    db.refresh(saved)
    logger.info("inbound mail settings updated: user_id=%s", user.id)
    return inbound_mail_out(saved)


@router.post("/inbound-mail-settings/test", status_code=204)
def test_inbound_mail_settings(db: Session = Depends(get_db), user: User = Depends(current_admin)):
    saved = db.get(InboundMailSettings, 1)
    if saved is None:
        raise HTTPException(422, "受信メール設定を保存してください。")
    try:
        client = open_mailbox(inbound_configuration(saved))
        client.logout()
    except InboundMailError as exc:
        logger.warning("inbound mail test failed: type=%s", type(exc).__name__)
        raise HTTPException(503, exc.public_message) from exc
    logger.info("inbound mail test succeeded: user_id=%s", user.id)


@router.post("/inbound-mail-settings/sync", response_model=InboundMailSyncOut)
def sync_inbound_mail_now(db: Session = Depends(get_db), user: User = Depends(current_admin)):
    saved = db.get(InboundMailSettings, 1)
    if saved is None or not saved.active:
        raise HTTPException(422, "受信メールの自動取込を有効にしてください。")
    try:
        processed = sync_inbound_mail(db, force=True, raise_on_error=True)
    except InboundMailError as exc:
        raise HTTPException(503, exc.public_message) from exc
    return InboundMailSyncOut(processed=processed)


@router.get("/inbound-emails", response_model=list[InboundEmailOut])
def list_inbound_emails(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    rows = db.execute(
        select(InboundEmail, Company.company_name)
        .outerjoin(Company, Company.id == InboundEmail.company_id)
        .order_by(InboundEmail.received_at.desc(), InboundEmail.id)
        .limit(min(max(limit, 1), 100))
    ).all()
    return [
        InboundEmailOut(
            id=item.id,
            sender_email=item.sender_email,
            subject=item.subject,
            preview=item.preview,
            received_at=item.received_at,
            company_id=item.company_id,
            company_name=company_name or "",
            match_type=item.match_type,
        )
        for item, company_name in rows
    ]
