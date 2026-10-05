"""Explicit human-selected callback methods; never infer an email address field."""

from app.services.form_intelligence.rules import normalize


def contact_method_channel(options: list[dict], value: str) -> str | None:
    if not value:
        return None
    matches = [o for o in options if str(o.get("value") or "") == value]
    if len(matches) != 1:
        return None
    aliases = {
        "メール": "email",
        "メールでの連絡": "email",
        "メールで連絡": "email",
        "メールアドレス": "email",
        "email": "email",
        "e-mail": "email",
        "mail": "email",
        "電話": "phone",
        "電話での連絡": "phone",
        "電話で連絡": "phone",
        "電話番号": "phone",
        "tel": "phone",
        "phone": "phone",
        "telephone": "phone",
    }
    option = matches[0]
    label = normalize(str(option.get("label") or ""))
    label_channel = aliases.get(label)
    value_channel = aliases.get(normalize(value))
    if label and not label_channel:
        return None
    if label_channel and value_channel and label_channel != value_channel:
        return None
    return label_channel or value_channel


def contact_method_review_reason(field: dict) -> str:
    value = str(field.get("recommended_value") or "")
    if (
        field["field_type"] not in {"radio", "select"}
        or field.get("decision_source") != "MANUAL"
        or not contact_method_channel(field.get("options", []), value)
    ):
        return "連絡方法の選択値を人が確認・保存してください。"
    return ""


def sender_contact_review_reason(fields: list[dict], sources: dict[str, str]) -> str:
    for field in fields:
        if field["mapped_key"] != "contact_method":
            continue
        reason = contact_method_review_reason(field)
        if reason:
            return reason
        channel = contact_method_channel(
            field.get("options", []), str(field.get("recommended_value") or "")
        )
        if channel and not sources.get(channel, "").strip():
            return "選択した連絡方法に対応する送信者のメール・電話を設定してください。"
    return ""
