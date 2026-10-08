"""Non-delivery SMTP diagnostics. Never issue MAIL, RCPT, DATA or send_message."""

import smtplib
import ssl
from datetime import datetime, timezone

from app.schema_settings import SmtpConnectionTestOut
from app.services.email_delivery import EmailDeliveryError, smtp_configuration


def check_smtp_connection(db) -> SmtpConnectionTestOut:
    stage = "configuration"
    tls = authenticated = False

    def result(ok: bool, message: str) -> SmtpConnectionTestOut:
        return SmtpConnectionTestOut(
            ok=ok,
            stage=stage,
            message=message,
            tls_verified=tls,
            authenticated=authenticated,
            checked_at=datetime.now(timezone.utc),
        )

    try:
        config = smtp_configuration(db)
    except EmailDeliveryError:
        return result(False, "保存されたSMTP設定を読み込めません。暗号化設定を確認してください。")
    if not config.host:
        return result(False, "SMTP設定を保存してから接続確認を行ってください。")
    if config.port == 465:
        return result(
            False, "送信経路はSTARTTLS方式です。提供元のSTARTTLS用ポートを設定してください。"
        )
    if config.username and (not config.use_starttls or not config.password):
        return result(False, "認証にはSTARTTLSと保存済みパスワードが必要です。")
    stage = "connection"
    try:
        with smtplib.SMTP(
            config.host, config.port, timeout=min(config.timeout_seconds, 15)
        ) as client:
            stage = "greeting"
            code, _ = client.ehlo()
            if code != 250:
                return result(False, "SMTPサーバーの応答を確認できませんでした。")
            if config.use_starttls:
                stage = "tls"
                client.starttls(context=ssl.create_default_context())
                tls = True
                code, _ = client.ehlo()
                if code != 250:
                    return result(False, "暗号化後のSMTPサーバー応答を確認できませんでした。")
            if config.username:
                stage = "authentication"
                client.login(config.username, config.password)
                authenticated = True
            stage = "completed"
    except smtplib.SMTPAuthenticationError:
        return result(
            False,
            "SMTP認証に失敗しました。ユーザー名・パスワード・認証設定を確認してください。",
        )
    except (OSError, smtplib.SMTPException):
        return result(
            False,
            {
                "connection": "接続できません。SMTPホスト・ポート・通信環境を確認してください。",
                "tls": "暗号化接続を確認できません。証明書・STARTTLS対応を確認してください。",
            }.get(stage, "SMTP接続確認に失敗しました。提供元の接続設定を確認してください。"),
        )
    return result(
        True,
        "接続・認証を確認しました。メールは送信していません。"
        if authenticated
        else "接続を確認しました。認証は未実施です。メールは送信していません。",
    )
