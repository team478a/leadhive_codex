from contextlib import AbstractContextManager

import pytest

from app.services import form_delivery, form_delivery_result
from app.services.form_delivery import FormDeliveryError, submit_form
from app.services.scraper import FetchedPage

INITIAL_FORM = """
<form action="/contact" method="post">
  <input type="hidden" name="csrf" value="initial-token">
  <input name="name" required>
  <textarea name="message" required></textarea>
  <button type="submit">確認</button>
</form>
"""


class FakeResponse(AbstractContextManager):
    def __init__(self, url: str, status: int, html: str = "", location: str = ""):
        self.url = url
        self.status_code = status
        self.headers = {"content-type": "text/html; charset=utf-8"}
        if location:
            self.headers["location"] = location
        self.encoding = "utf-8"
        self._content = html.encode()

    def iter_bytes(self):
        yield self._content

    def __exit__(self, *_args):
        return False


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []

    def stream(self, method, url, data=None, follow_redirects=False):
        assert follow_redirects is False
        self.calls.append((method, url, data))
        return self.responses.pop(0)


class FakeFetcher:
    responses: list[FakeResponse] = []
    instance = None

    def __init__(self):
        self.client = FakeClient(list(self.responses))
        type(self).instance = self

    def fetch_html(self, url):
        return FetchedPage(url, INITIAL_FORM)

    def close(self):
        pass


def run_submission(monkeypatch, responses, *, confirmation_expected=False):
    FakeFetcher.responses = responses
    monkeypatch.setattr(form_delivery, "SafeFetcher", FakeFetcher)
    monkeypatch.setattr(form_delivery_result, "validate_public_url", lambda url: url)
    return submit_form(
        "https://example.com/contact",
        {"name": "営業担当", "message": "お問い合わせ本文"},
        confirmation_expected=confirmation_expected,
    )


def test_direct_submission_requires_positive_completion_evidence(monkeypatch):
    preview, result = run_submission(
        monkeypatch,
        [FakeResponse("https://example.com/thanks", 200, "<h1>送信完了しました</h1>")],
    )
    assert preview.action_url == "https://example.com/contact"
    assert result.completion_evidence == "送信完了メッセージ"
    assert result.final_url == "https://example.com/thanks"
    assert result.confirmation_used is False


def test_confirmation_page_is_submitted_once_and_verified(monkeypatch):
    confirmation = """
    <h1>入力内容の確認</h1>
    <form action="/contact/send" method="post">
      <input type="hidden" name="csrf" value="final-token">
      <button type="submit" name="action" value="back">戻る</button>
      <button type="submit" name="action" value="send">送信する</button>
    </form>
    """
    _, result = run_submission(
        monkeypatch,
        [
            FakeResponse("https://example.com/contact/confirm", 200, confirmation),
            FakeResponse("https://example.com/contact/complete", 200, "受付が完了しました"),
        ],
        confirmation_expected=True,
    )
    assert result.confirmation_used is True
    assert result.completion_evidence == "送信完了URL"
    assert FakeFetcher.instance.client.calls[1] == (
        "POST",
        "https://example.com/contact/send",
        {"csrf": "final-token", "action": "send"},
    )


def test_redirect_is_followed_only_on_same_host(monkeypatch):
    _, result = run_submission(
        monkeypatch,
        [
            FakeResponse("https://example.com/contact", 303, location="/thanks"),
            FakeResponse("https://example.com/thanks", 200, "Thank you for your message"),
        ],
    )
    assert result.final_url == "https://example.com/thanks"
    assert FakeFetcher.instance.client.calls[1][0] == "GET"


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            FakeResponse("https://example.com/contact", 200, "送信内容をご確認ください"),
            "manual_required",
        ),
        (
            FakeResponse("https://example.com/contact", 200, "入力内容に誤りがあります"),
            "validation_error",
        ),
        (
            FakeResponse("https://other.example/thanks", 200, "送信完了しました"),
            "manual_required",
        ),
    ],
)
def test_unverified_results_are_never_marked_submitted(monkeypatch, response, expected_code):
    with pytest.raises(FormDeliveryError) as error:
        run_submission(monkeypatch, [response])
    assert error.value.code == expected_code


def test_unexpected_confirmation_page_requires_reanalysis(monkeypatch):
    confirmation = """
    <form action="/send" method="post">
      <input type="hidden" name="token" value="x">
      <button type="submit">送信</button>
    </form>
    """
    with pytest.raises(FormDeliveryError) as error:
        run_submission(
            monkeypatch,
            [FakeResponse("https://example.com/confirm", 200, confirmation)],
        )
    assert error.value.code == "profile_changed"


def test_external_confirmation_action_is_blocked(monkeypatch):
    confirmation = """
    <form action="https://other.example/send" method="post">
      <input type="hidden" name="token" value="x">
      <button type="submit">送信</button>
    </form>
    """
    with pytest.raises(FormDeliveryError) as error:
        run_submission(
            monkeypatch,
            [FakeResponse("https://example.com/confirm", 200, confirmation)],
            confirmation_expected=True,
        )
    assert error.value.code == "manual_required"
