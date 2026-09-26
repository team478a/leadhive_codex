from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from bs4 import BeautifulSoup

from app.services.form_delivery_result import (
    FormDeliveryError,
    FormSubmissionResult,
    submit_and_verify,
)
from app.services.form_intelligence.analyzer import parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.scraper import SafeFetcher, ScrapeError


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    field_type: str
    required: bool
    value: str
    options: list[str]
    mapped_key: str = "unknown"
    confidence: float = 0
    decision_source: str = ""


@dataclass(frozen=True)
class FormPreview:
    form_url: str
    action_url: str
    fields: list[FormField]
    form_profile_id: UUID | None = None
    form_status: str = "UNANALYZED"
    fingerprint: str = ""


def _label(element, form) -> str:
    field_id = element.get("id")
    if field_id:
        label = form.select_one(f"label[for='{field_id}']")
        if label:
            return label.get_text(" ", strip=True)[:200]
    parent = element.find_parent("label")
    if parent:
        return parent.get_text(" ", strip=True)[:200]
    return str(element.get("placeholder") or element.get("name") or "入力項目")[:200]


def _has_captcha(form) -> bool:
    text = str(form).lower()
    return any(value in text for value in ("captcha", "recaptcha", "hcaptcha", "turnstile"))


def _profile_metadata(profile_fields: list[Any] | None) -> dict[str, Any]:
    return {
        str(field.name): field for field in profile_fields or [] if str(getattr(field, "name", ""))
    }


def _option_value(option) -> str:
    if option.has_attr("value"):
        return str(option.get("value") or "")[:200]
    return option.get_text(" ", strip=True)[:200]


def _submit_payload(form) -> dict[str, str]:
    controls = []
    for control in form.select("button, input[type='submit'], input[type='image']"):
        if control.name == "button" and str(control.get("type") or "submit").lower() != "submit":
            continue
        label = str(control.get_text(" ", strip=True) or control.get("value") or "").lower()
        if any(value in label for value in ("戻る", "修正", "キャンセル", "back", "edit")):
            continue
        controls.append((control, label))
    preferred = [
        control
        for control, label in controls
        if any(value in label for value in ("送信", "確認", "submit", "send", "confirm", "次へ"))
    ]
    selected = (
        preferred[0] if len(preferred) == 1 else controls[0][0] if len(controls) == 1 else None
    )
    if selected is None or not selected.get("name"):
        return {}
    return {str(selected.get("name")): str(selected.get("value") or "")}


def _parse_form(
    html: str,
    form_url: str,
    *,
    form_index: int = 0,
    profile_fields: list[Any] | None = None,
    form_profile_id: UUID | None = None,
    form_status: str = "UNANALYZED",
) -> FormPreview:
    soup = BeautifulSoup(html, "html.parser")
    forms = list(soup.select("form"))
    if form_index < 0 or form_index >= len(forms):
        raise FormDeliveryError(
            "解析済みのフォームが見つかりません。再解析してください。", "profile_changed"
        )
    form = forms[form_index]
    if (form.get("method") or "get").lower() != "post":
        raise FormDeliveryError("選択したフォームはPOST形式ではありません。", "unsupported")
    if _has_captcha(form):
        raise FormDeliveryError(
            "CAPTCHA付きフォームは自動送信できません。Codex支援を利用してください。",
            "manual_required",
        )
    if str(form.get("enctype") or "").lower() == "multipart/form-data":
        raise FormDeliveryError(
            "ファイル送信用フォームは自動送信できません。Codex支援を利用してください。",
            "manual_required",
        )
    action_url = urljoin(form_url, str(form.get("action") or form_url))
    origin = urlsplit(form_url).hostname
    if (
        urlsplit(action_url).scheme not in {"http", "https"}
        or urlsplit(action_url).hostname != origin
    ):
        raise FormDeliveryError(
            "外部サイトへ送信するフォームは自動送信できません。", "manual_required"
        )
    analysis_fields = parse_form_fields(form)
    fingerprint = form_fingerprint(analysis_fields)
    metadata = _profile_metadata(profile_fields)
    fields: list[FormField] = []
    grouped: set[tuple[str, str]] = set()
    for element in form.select("input[name], textarea[name], select[name]"):
        if element.has_attr("disabled"):
            continue
        name = str(element.get("name") or "").strip()
        raw_type = str(element.get("type") or "text").lower()
        if not name or raw_type in {"submit", "button", "reset", "image"}:
            continue
        if raw_type in {"file", "password"}:
            raise FormDeliveryError(
                "ファイルまたはパスワード入力を含むフォームは自動送信できません。",
                "manual_required",
            )
        profile_field = metadata.get(name)
        if raw_type in {"checkbox", "radio"}:
            group_key = (raw_type, name)
            if group_key in grouped:
                continue
            grouped.add(group_key)
            group = [
                item
                for item in form.select("input[name]")
                if str(item.get("type") or "text").lower() == raw_type
                and str(item.get("name") or "").strip() == name
            ]
            options = [_option_value(item) or "on" for item in group]
            selected = next((item for item in group if item.has_attr("checked")), None)
            value = _option_value(selected) if selected else ""
            if profile_field and getattr(profile_field, "recommended_value", ""):
                value = str(profile_field.recommended_value)
            fields.append(
                FormField(
                    name=name,
                    label=_label(element, form),
                    field_type="select",
                    required=(
                        any(
                            item.has_attr("required")
                            or str(item.get("aria-required") or "").lower() == "true"
                            for item in group
                        )
                        or bool(getattr(profile_field, "required", False))
                    ),
                    value=value[:2000],
                    options=list(dict.fromkeys(options)),
                    mapped_key=str(getattr(profile_field, "mapped_key", "unknown")),
                    confidence=float(getattr(profile_field, "confidence", 0)),
                    decision_source=str(getattr(profile_field, "decision_source", "")),
                )
            )
            continue
        if element.name == "textarea":
            field_type = "textarea"
        elif element.name == "select":
            field_type = "select"
        elif raw_type in {"email", "tel"}:
            field_type = raw_type
        elif raw_type == "hidden":
            continue
        else:
            field_type = "text"
        options = [value for option in element.select("option") if (value := _option_value(option))]
        if element.name == "textarea":
            value = element.get_text()
        elif element.name == "select":
            selected = element.select_one("option[selected]") or element.select_one("option")
            value = _option_value(selected) if selected else ""
        else:
            value = str(element.get("value") or "")
        if profile_field and getattr(profile_field, "recommended_value", ""):
            value = str(profile_field.recommended_value)
        fields.append(
            FormField(
                name=name,
                label=_label(element, form),
                field_type=field_type,
                required=(
                    element.has_attr("required")
                    or str(element.get("aria-required") or "").lower() == "true"
                    or bool(getattr(profile_field, "required", False))
                ),
                value=value[:2000],
                options=options,
                mapped_key=str(getattr(profile_field, "mapped_key", "unknown")),
                confidence=float(getattr(profile_field, "confidence", 0)),
                decision_source=str(getattr(profile_field, "decision_source", "")),
            )
        )
    if not fields:
        raise FormDeliveryError("入力できるフォーム項目が見つかりません。")
    return FormPreview(
        form_url=form_url,
        action_url=action_url,
        fields=fields,
        form_profile_id=form_profile_id,
        form_status=form_status,
        fingerprint=fingerprint,
    )


def inspect_form(
    form_url: str,
    *,
    form_index: int = 0,
    profile_fields: list[Any] | None = None,
    form_profile_id: UUID | None = None,
    form_status: str = "UNANALYZED",
) -> FormPreview:
    fetcher = SafeFetcher()
    try:
        page = fetcher.fetch_html(form_url)
        return _parse_form(
            page.html,
            page.url,
            form_index=form_index,
            profile_fields=profile_fields,
            form_profile_id=form_profile_id,
            form_status=form_status,
        )
    except ScrapeError as exc:
        raise FormDeliveryError(exc.public_message) from exc
    finally:
        fetcher.close()


def submit_form(
    form_url: str,
    values: dict[str, str],
    *,
    form_index: int = 0,
    profile_fields: list[Any] | None = None,
    form_profile_id: UUID | None = None,
    expected_fingerprint: str = "",
    confirmation_expected: bool = False,
) -> tuple[FormPreview, FormSubmissionResult]:
    fetcher = SafeFetcher()
    try:
        page = fetcher.fetch_html(form_url)
        preview = _parse_form(
            page.html,
            page.url,
            form_index=form_index,
            profile_fields=profile_fields,
            form_profile_id=form_profile_id,
            form_status="READY",
        )
        if expected_fingerprint and preview.fingerprint != expected_fingerprint:
            raise FormDeliveryError(
                "フォーム構造が解析時から変更されています。再解析してください。",
                "profile_changed",
            )
        missing = [
            field.label
            for field in preview.fields
            if field.required and not values.get(field.name, "").strip()
        ]
        if missing:
            raise FormDeliveryError(f"必須項目を入力してください: {', '.join(missing[:3])}")
        allowed = {field.name for field in preview.fields}
        soup = BeautifulSoup(page.html, "html.parser")
        forms = list(soup.select("form"))
        form = forms[form_index] if form_index < len(forms) else None
        hidden = (
            {
                str(item.get("name")): str(item.get("value") or "")
                for item in form.select("input[type='hidden'][name]")
            }
            if form
            else {}
        )
        payload = (
            hidden
            | {key: value[:2000] for key, value in values.items() if key in allowed}
            | (_submit_payload(form) if form else {})
        )
        submission = submit_and_verify(
            fetcher,
            preview.action_url,
            payload,
            original_form_url=preview.form_url,
            confirmation_expected=confirmation_expected,
        )
        return preview, submission
    except ScrapeError as exc:
        raise FormDeliveryError(exc.public_message) from exc
    finally:
        fetcher.close()
