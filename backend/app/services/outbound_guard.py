"""Instance-wide outbound stop, independent of Agent and approval settings."""

import logging

from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger("leadhive")


def require_outbound_enabled() -> None:
    if not settings.outbound_enabled:
        logger.warning("outbound execution denied: instance sending disabled")
        raise HTTPException(
            503, "この環境では外部送信を停止しています。収集・解析・文面準備は利用できます。"
        )


def require_legacy_form_enabled() -> None:
    require_outbound_enabled()
    if not settings.legacy_form_delivery_enabled or settings.human_approved_form_enabled:
        raise HTTPException(
            403, "旧フォーム送信経路は停止中です。承認キューで準備・承認してください。"
        )
