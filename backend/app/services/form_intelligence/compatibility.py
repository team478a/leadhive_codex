from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4.element import Tag


@dataclass(frozen=True)
class DeliveryCompatibility:
    supported: bool
    reason: str = ""


def assess_delivery_compatibility(form: Tag, page_url: str) -> DeliveryCompatibility:
    if (form.get("method") or "get").lower() != "post":
        return DeliveryCompatibility(False, "POST形式ではないためCodex支援が必要です。")
    if str(form.get("enctype") or "").lower() == "multipart/form-data":
        return DeliveryCompatibility(False, "ファイル送信用フォームはCodex支援が必要です。")

    action_url = urljoin(page_url, str(form.get("action") or page_url))
    action = urlsplit(action_url)
    page = urlsplit(page_url)
    if action.scheme not in {"http", "https"} or action.hostname != page.hostname:
        return DeliveryCompatibility(False, "外部サイトへ送信するフォームです。")
    if page.scheme == "https" and action.scheme != "https":
        return DeliveryCompatibility(False, "安全でない通信へ送信するフォームです。")

    for field in form.select("input, textarea, select"):
        if field.has_attr("disabled"):
            continue
        field_type = str(field.get("type") or "text").lower()
        if field_type in {"submit", "button", "reset", "image"}:
            continue
        if field_type in {"file", "password"}:
            return DeliveryCompatibility(
                False,
                "ファイルまたはパスワード入力があるためCodex支援が必要です。",
            )
        if field_type != "hidden" and not str(field.get("name") or "").strip():
            return DeliveryCompatibility(
                False,
                "送信項目にname属性がないためブラウザ操作が必要です。",
            )
    return DeliveryCompatibility(True)
