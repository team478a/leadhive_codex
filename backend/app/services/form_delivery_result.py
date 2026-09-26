import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.config import settings
from app.services.scraper import SafeFetcher, ScrapeError, validate_public_url


class FormDeliveryError(Exception):
    def __init__(self, public_message: str, code: str = ""):
        super().__init__(public_message)
        self.public_message = public_message
        self.code = code


@dataclass(frozen=True)
class FormSubmissionResult:
    response_status: int
    final_url: str
    confirmation_used: bool
    completion_evidence: str


@dataclass(frozen=True)
class _ResponsePage:
    url: str
    status_code: int
    html: str


_SUCCESS_PATTERNS = (
    (re.compile(r"送信.{0,8}(?:完了|成功|しました)"), "送信完了メッセージ"),
    (re.compile(r"(?:お問い?合わせ|ご連絡).{0,12}(?:受け付け|受付|承り)"), "受付完了メッセージ"),
    (re.compile(r"(?:お問い?合わせ|送信).{0,12}ありがとう"), "お礼メッセージ"),
    (re.compile(r"thank\s+you.{0,40}(?:message|inquiry|contact)", re.I), "Thank-youメッセージ"),
    (
        re.compile(r"(?:message|submission).{0,20}(?:sent|successful|received)", re.I),
        "完了メッセージ",
    ),
    (re.compile(r"we\s+have\s+received\s+your", re.I), "受付完了メッセージ"),
)
_ERROR_PATTERNS = (
    re.compile(r"入力内容.{0,12}(?:誤り|エラー)"),
    re.compile(r"(?:入力|送信).{0,12}(?:失敗|エラー)"),
    re.compile(r"正しく入力"),
    re.compile(r"必須項目.{0,12}(?:入力|選択)"),
    re.compile(r"validation\s+error", re.I),
    re.compile(r"(?:field\s+is|required\s+field).{0,20}required", re.I),
    re.compile(r"please\s+(?:enter|select).{0,30}(?:required|field)", re.I),
)
_SUCCESS_PATH_PATTERN = re.compile(
    r"(?:^|[-_/])(?:thanks?|thank-you|complete(?:d)?|success|sent)(?:[-_/]|$)", re.I
)
_POSITIVE_SUBMIT_PATTERN = re.compile(
    r"^(?:送信|送信する|確定|確定する|申し込む|申込む|submit|send)(?:\s.*)?$", re.I
)
_NEGATIVE_SUBMIT_PATTERN = re.compile(r"戻る|修正|キャンセル|back|edit|cancel|確認|次へ", re.I)


def _has_captcha(form) -> bool:
    text = str(form).lower()
    return any(value in text for value in ("captcha", "recaptcha", "hcaptcha", "turnstile"))


def _same_delivery_origin(candidate_url: str, original_url: str) -> str:
    try:
        normalized = validate_public_url(candidate_url)
    except ScrapeError as exc:
        raise FormDeliveryError(exc.public_message, "manual_required") from exc
    candidate = urlsplit(normalized)
    original = urlsplit(original_url)
    if candidate.hostname != original.hostname:
        raise FormDeliveryError(
            "外部サイトへの遷移を検出したため、送信完了を自動判定できません。",
            "manual_required",
        )
    if original.scheme == "https" and candidate.scheme != "https":
        raise FormDeliveryError(
            "安全でない通信への遷移を検出したため、送信を停止しました。",
            "manual_required",
        )
    return normalized


def _read_response(response) -> _ResponsePage:
    if response.status_code >= 400:
        raise FormDeliveryError(
            f"フォームへの送信に失敗しました（HTTP {response.status_code}）。",
            "delivery_failed",
        )
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.scraper_max_bytes:
        raise FormDeliveryError("送信結果のデータサイズが上限を超えました。", "manual_required")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > settings.scraper_max_bytes:
            raise FormDeliveryError("送信結果のデータサイズが上限を超えました。", "manual_required")
        chunks.append(chunk)
    encoding = response.encoding or "utf-8"
    return _ResponsePage(
        url=str(response.url),
        status_code=response.status_code,
        html=b"".join(chunks).decode(encoding, errors="replace"),
    )


def _request_result(
    fetcher: SafeFetcher, method: str, url: str, payload: dict[str, str]
) -> _ResponsePage:
    current_url = url
    current_method = method
    current_payload = payload
    for _ in range(6):
        normalized = _same_delivery_origin(current_url, url)
        try:
            with fetcher.client.stream(
                current_method,
                normalized,
                data=current_payload if current_method == "POST" else None,
                follow_redirects=False,
            ) as response:
                status_code = response.status_code
                if status_code in {307, 308}:
                    raise FormDeliveryError(
                        "送信先がフォームの再送信を要求したため、自動処理を停止しました。",
                        "manual_required",
                    )
                if status_code in {301, 302, 303}:
                    location = response.headers.get("location")
                    if not location:
                        raise FormDeliveryError(
                            "送信後の遷移先が不明なため、完了を確認できません。",
                            "manual_required",
                        )
                    current_url = urljoin(normalized, location)
                    current_method = "GET"
                    current_payload = {}
                    continue
                page = _read_response(response)
                _same_delivery_origin(page.url, url)
                return page
        except FormDeliveryError:
            raise
        except Exception as exc:
            raise FormDeliveryError("フォームへの送信に失敗しました。", "delivery_failed") from exc
    raise FormDeliveryError("送信後のリダイレクト回数が上限を超えました。", "manual_required")


def _page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.select("script, style, noscript, svg, template"):
        element.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def _completion_evidence(page: _ResponsePage) -> str:
    text = _page_text(page.html)
    for pattern, evidence in _SUCCESS_PATTERNS:
        if pattern.search(text):
            return evidence
    if _SUCCESS_PATH_PATTERN.search(urlsplit(page.url).path):
        return "送信完了URL"
    return ""


def _has_validation_error(page: _ResponsePage) -> bool:
    text = _page_text(page.html)
    return any(pattern.search(text) for pattern in _ERROR_PATTERNS)


def _confirmation_payload(page: _ResponsePage) -> tuple[str, dict[str, str]] | None:
    soup = BeautifulSoup(page.html, "html.parser")
    candidates: list[tuple[str, dict[str, str]]] = []
    for form in soup.select("form"):
        if (form.get("method") or "get").lower() != "post" or _has_captcha(form):
            continue
        unsupported = False
        for field in form.select("input[name], textarea[name], select[name]"):
            raw_type = str(field.get("type") or "text").lower()
            if field.name in {"textarea", "select"} or raw_type not in {
                "hidden",
                "submit",
                "button",
                "reset",
                "image",
            }:
                unsupported = True
                break
        if unsupported:
            continue
        submit_controls = []
        for control in form.select("button, input[type='submit'], input[type='image']"):
            label = re.sub(
                r"\s+",
                " ",
                str(control.get("value") or control.get_text(" ", strip=True)),
            ).strip()
            if (
                label
                and _POSITIVE_SUBMIT_PATTERN.search(label)
                and not _NEGATIVE_SUBMIT_PATTERN.search(label)
            ):
                submit_controls.append(control)
        if len(submit_controls) != 1:
            continue
        payload = {
            str(field.get("name")): str(field.get("value") or "")
            for field in form.select("input[type='hidden'][name]")
        }
        submit_control = submit_controls[0]
        if submit_control.get("name"):
            payload[str(submit_control.get("name"))] = str(submit_control.get("value") or "")
        candidates.append((urljoin(page.url, str(form.get("action") or page.url)), payload))
    return candidates[0] if len(candidates) == 1 else None


def submit_and_verify(
    fetcher: SafeFetcher,
    action_url: str,
    payload: dict[str, str],
    *,
    original_form_url: str,
    confirmation_expected: bool,
) -> FormSubmissionResult:
    result_page = _request_result(fetcher, "POST", action_url, payload)
    if _has_validation_error(result_page):
        raise FormDeliveryError(
            "フォームの入力エラーが返されました。入力内容を確認してください。",
            "validation_error",
        )
    evidence = _completion_evidence(result_page)
    if evidence:
        return FormSubmissionResult(result_page.status_code, result_page.url, False, evidence)

    confirmation = _confirmation_payload(result_page)
    if confirmation is None:
        raise FormDeliveryError(
            "送信完了を確認できませんでした。Codex支援で結果を確認してください。",
            "manual_required",
        )
    if not confirmation_expected:
        raise FormDeliveryError(
            "解析時にはなかった確認画面を検出しました。再解析してください。",
            "profile_changed",
        )
    confirmation_url, confirmation_values = confirmation
    confirmation_url = _same_delivery_origin(confirmation_url, original_form_url)
    final_page = _request_result(fetcher, "POST", confirmation_url, confirmation_values)
    if _has_validation_error(final_page):
        raise FormDeliveryError(
            "最終送信後に入力エラーが返されました。Codex支援で確認してください。",
            "validation_error",
        )
    evidence = _completion_evidence(final_page)
    if not evidence:
        raise FormDeliveryError(
            "最終送信後の完了を確認できませんでした。Codex支援で結果を確認してください。",
            "manual_required",
        )
    return FormSubmissionResult(final_page.status_code, final_page.url, True, evidence)
