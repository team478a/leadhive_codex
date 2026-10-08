import re
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

    if (
        "wpcf7-form" in form.get("class", [])
        or form.select_one('input[name="_wpcf7"]')
        or form.find_parent(class_="wpcf7")
    ):
        return DeliveryCompatibility(
            False,
            "Contact Form 7の送信経路は未対応です。ブラウザで確認してください。",
        )
    if (
        str(form.get("onsubmit") or "").strip()
        or any(
            form.has_attr(name) and str(form.get(name) or "").lower() not in {"false", "0"}
            for name in ("data-ajax", "data-remote")
        )
        or form.has_attr("hx-post")
        or any(str(name).startswith(("x-on:submit", "@submit", "on:submit")) for name in form.attrs)
    ):
        return DeliveryCompatibility(
            False, "JavaScript・非同期の送信経路は未検証です。ブラウザでの確認が必要です。"
        )
    native_submit = []
    for control in form.select("button, input"):
        if control.has_attr("disabled"):
            continue
        kind = str(
            control.get("type") or ("submit" if control.name == "button" else "text")
        ).lower()
        label = control.get_text(" ", strip=True) or str(control.get("value") or "")
        if kind == "button" and re.search(r"確認|送信|次へ|confirm|submit|send|next", label, re.I):
            return DeliveryCompatibility(
                False, "確認・送信ボタンがJavaScript操作を必要とします。確認経路は未検証です。"
            )
        if kind == "submit":
            if str(control.get("onclick") or "").strip() or any(
                control.has_attr(name) for name in ("formaction", "formmethod", "formenctype")
            ):
                return DeliveryCompatibility(
                    False,
                    "送信ボタンに独自処理または送信先の上書きがあります。ブラウザでの確認が必要です。",
                )
            native_submit.append(control)
    names: dict[str, str] = {}
    visible_count = 0
    for field in form.select("input, textarea, select"):
        if field.has_attr("disabled"):
            continue
        field_type = str(field.get("type") or "text").lower()
        if field_type in {"submit", "button", "reset", "image"}:
            continue
        if field.name == "select" and field.has_attr("multiple"):
            return DeliveryCompatibility(False, "複数選択項目は人による確認が必要です。")
        name = str(field.get("name") or "").strip()
        if name and name in names and not (field_type == names[name] == "radio"):
            return DeliveryCompatibility(False, "同名の複数入力項目は人による確認が必要です。")
        if name:
            names[name] = field_type
        if field_type != "hidden":
            visible_count += 1
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
    if not visible_count:
        return DeliveryCompatibility(False, "入力項目がないため人による確認が必要です。")
    if not native_submit:
        return DeliveryCompatibility(
            False, "標準の送信ボタンを確認できません。ブラウザ操作が必要です。"
        )
    return DeliveryCompatibility(True)
