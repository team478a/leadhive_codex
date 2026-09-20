from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.services.scraper import SafeFetcher, ScrapeError


class FormDeliveryError(Exception):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    field_type: str
    required: bool
    value: str
    options: list[str]


@dataclass(frozen=True)
class FormPreview:
    form_url: str
    action_url: str
    fields: list[FormField]


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


def _parse_form(html: str, form_url: str) -> FormPreview:
    soup = BeautifulSoup(html, "html.parser")
    forms = [
        form for form in soup.select("form") if (form.get("method") or "get").lower() == "post"
    ]
    if not forms:
        raise FormDeliveryError("送信できるPOST形式のフォームが見つかりません。")
    form = forms[0]
    if _has_captcha(form):
        raise FormDeliveryError("CAPTCHA付きフォームは自動送信できません。手動で送信してください。")
    action_url = urljoin(form_url, str(form.get("action") or form_url))
    origin = urlsplit(form_url).hostname
    if (
        urlsplit(action_url).scheme not in {"http", "https"}
        or urlsplit(action_url).hostname != origin
    ):
        raise FormDeliveryError("外部サイトへ送信するフォームは自動送信できません。")
    fields: list[FormField] = []
    for element in form.select("input[name], textarea[name], select[name]"):
        if element.has_attr("disabled"):
            continue
        name = str(element.get("name") or "").strip()
        raw_type = str(element.get("type") or "text").lower()
        if not name or raw_type in {"submit", "button", "reset", "file", "image"}:
            continue
        if element.name == "textarea":
            field_type = "textarea"
        elif element.name == "select":
            field_type = "select"
        elif raw_type in {"email", "tel"}:
            field_type = raw_type
        elif raw_type == "hidden":
            continue
        elif raw_type in {"checkbox", "radio", "password"}:
            raise FormDeliveryError(
                "選択式またはパスワード入力を含むフォームは自動送信できません。"
            )
        else:
            field_type = "text"
        options = [option.get_text(" ", strip=True)[:200] for option in element.select("option")]
        value = (
            str(element.get("value") or "") if element.name != "textarea" else element.get_text()
        )
        fields.append(
            FormField(
                name=name,
                label=_label(element, form),
                field_type=field_type,
                required=element.has_attr("required"),
                value=value[:2000],
                options=options,
            )
        )
    if not fields:
        raise FormDeliveryError("入力できるフォーム項目が見つかりません。")
    return FormPreview(form_url=form_url, action_url=action_url, fields=fields)


def inspect_form(form_url: str) -> FormPreview:
    fetcher = SafeFetcher()
    try:
        page = fetcher.fetch_html(form_url)
        return _parse_form(page.html, page.url)
    except ScrapeError as exc:
        raise FormDeliveryError(exc.public_message) from exc
    finally:
        fetcher.close()


def submit_form(form_url: str, values: dict[str, str]) -> tuple[FormPreview, int]:
    fetcher = SafeFetcher()
    try:
        page = fetcher.fetch_html(form_url)
        preview = _parse_form(page.html, page.url)
        missing = [
            field.label
            for field in preview.fields
            if field.required and not values.get(field.name, "").strip()
        ]
        if missing:
            raise FormDeliveryError(f"必須項目を入力してください: {', '.join(missing[:3])}")
        allowed = {field.name for field in preview.fields}
        soup = BeautifulSoup(page.html, "html.parser")
        form = next(
            (
                item
                for item in soup.select("form")
                if (item.get("method") or "get").lower() == "post"
            ),
            None,
        )
        hidden = (
            {
                str(item.get("name")): str(item.get("value") or "")
                for item in form.select("input[type='hidden'][name]")
            }
            if form
            else {}
        )
        payload = hidden | {key: value[:2000] for key, value in values.items() if key in allowed}
        try:
            response = fetcher.client.post(preview.action_url, data=payload, follow_redirects=False)
        except Exception as exc:
            raise FormDeliveryError("フォームへの送信に失敗しました。") from exc
        if response.status_code >= 400:
            raise FormDeliveryError(
                f"フォームへの送信に失敗しました（HTTP {response.status_code}）。"
            )
        return preview, response.status_code
    except ScrapeError as exc:
        raise FormDeliveryError(exc.public_message) from exc
    finally:
        fetcher.close()
