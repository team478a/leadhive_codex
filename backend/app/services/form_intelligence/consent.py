"""Consent is an explicit human choice, never an inferred subscription."""

import re

from app.services.form_intelligence.rules import normalize

CONSENT_KEYS = {"privacy_consent", "newsletter_consent"}
CONSENT_POLICY_VERSION = "CONSENT_POLICY_V1"
_PRIVACY_MARKERS = ("個人情報", "プライバシー", "privacy")
_NEWSLETTER_MARKERS = (
    "メルマガ",
    "メールマガジン",
    "newsletter",
    "配信",
    "お知らせ",
    "キャンペーン",
    "広告",
)
_NEGATIVE_MARKERS = (
    "同意しない",
    "希望しない",
    "受け取らない",
    "拒否",
    "disagree",
    "decline",
    "unsubscribe",
    "not agree",
)


def _consent_text(field: dict) -> tuple[str, str]:
    options = field.get("options", [])
    label = normalize(str(field.get("label") or ""))
    text = normalize(
        " ".join(
            [
                label,
                *(str(option.get("label") or "") for option in options if isinstance(option, dict)),
            ]
        )
    )
    return label, text


def consent_policy_category(field: dict) -> str:
    """Classify a consent field for Q1 metrics using CONSENT_POLICY_V1 conditions."""
    options = field.get("options", [])
    label, text = _consent_text(field)
    privacy = any(word in text for word in _PRIVACY_MARKERS)
    newsletter = any(word in text for word in _NEWSLETTER_MARKERS)
    if privacy and newsletter:
        return "mixed_privacy_newsletter"
    if (
        field.get("mapped_key") == "privacy_consent"
        and field.get("field_type") == "checkbox"
        and len(options) == 1
        and isinstance(options[0], dict)
        and bool(str(options[0].get("value") or "").strip())
        and privacy
        and not newsletter
        and not any(word in text for word in _NEGATIVE_MARKERS)
        and "必須性未確認" not in label
    ):
        return "privacy_only_single_checkbox"
    return "other"


def consent_review_reason(field: dict) -> str:
    options = field.get("options", [])
    _, text = _consent_text(field)
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
