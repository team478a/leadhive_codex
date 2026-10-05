"""Consent is an explicit human choice, never an inferred subscription."""

import re

from app.services.form_intelligence.rules import normalize

CONSENT_KEYS = {"privacy_consent", "newsletter_consent"}


def consent_review_reason(field: dict) -> str:
    options = field.get("options", [])
    text = normalize(
        str(field.get("label") or "") + " " + " ".join(str(o.get("label") or "") for o in options)
    )
    privacy = any(word in text for word in ("プライバシー", "個人情報", "privacy"))
    newsletter = any(word in text for word in ("メルマガ", "メールマガジン", "newsletter"))
    if privacy and newsletter:
        return "個人情報同意とメルマガ登録が混在しています。人による確認が必要です。"
    if (
        field["field_type"] != "checkbox"
        or len(options) != 1
        or not str(options[0].get("value") or "").strip()
        or re.search(
            r"同意しない|希望しない|受け取らない|拒否|disagree|decline|unsubscribe|not agree", text
        )
    ):
        return "同意チェック欄の送信値・条件を確定できません。確認が必要です。"
    value = str(field.get("recommended_value") or "")
    if field.get("decision_source") != "MANUAL":
        return "同意内容を人が確認し、選択値または任意欄の未選択を保存してください。"
    if value and value != str(options[0].get("value") or ""):
        return "同意チェック欄の選択値が実際の選択肢と一致しません。"
    if field["required"] and not value:
        return "必須の同意チェック欄が未選択です。"
    return ""
