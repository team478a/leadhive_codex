import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SmtpSettings, User
from app.schemas import SmtpSettingsInput, SmtpSettingsOut, SmtpTestInput
from app.security import current_admin
from app.services.email_delivery import EmailDeliveryError, encrypt_secret, send_test_email

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
        password_configured=bool(value.password_ciphertext),
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
