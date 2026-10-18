from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from bs4 import BeautifulSoup

from app.config import Settings
from app.services.browser_form_analysis import eligible_no_form_profile, inspect_rendered_dom
from browser_worker.jobs import _same_site_interval
from browser_worker.network_proxy import BrowserNetworkPolicy
from browser_worker.runtime import _safe_dom_script, is_read_only_request

FIXTURE = Path(__file__).parents[1] / "browser_worker" / "fixtures" / "browser_analysis_matrix.html"


def test_rendered_dom_reuses_form_compatibility_captcha_and_confirmation_rules():
    results = inspect_rendered_dom(
        FIXTURE.read_text(encoding="utf-8"), "https://fixture.example/contact"
    )

    assert [result.compatibility.reason_code for result in results] == [
        "CONTACT_FORM_7",
        "MULTIPART_OR_FILE",
        "JAVASCRIPT_CONFIRMATION",
        "ASYNC_SUBMISSION",
    ]
    assert results[0].captcha_type == "CAPTCHA_RECAPTCHA_V2"
    assert results[2].confirmation_page is True
    assert all(len(result.fingerprint) == 64 for result in results)
    assert all(result.form_found for result in results)


def test_rendered_dom_detects_embed_without_opening_external_embed():
    html = """<!doctype html><html><body><h1>お問い合わせ</h1>
    <iframe src="https://forms.vendor.example/form/abc"></iframe>
    <script src="https://js.hsforms.net/forms/embed/v2.js"></script>
    </body></html>"""

    result = inspect_rendered_dom(html, "https://fixture.example/contact")[0]

    assert not result.form_found
    assert "外部埋め込みを検出しました" in result.review_reason
    assert len(result.fingerprint) == 64


def test_no_form_candidates_require_known_contact_path_or_unverified_embed():
    company = SimpleNamespace(contact_url="")
    profile = SimpleNamespace(
        form_found=False,
        error_message="",
        form_url="https://fixture.example/about",
        review_reason="送信可能なフォームが見つかりません。",
    )

    assert not eligible_no_form_profile(company, profile)
    profile.form_url = "https://fixture.example/contact-us"
    assert eligible_no_form_profile(company, profile)
    profile.form_url = "https://fixture.example/about"
    profile.review_reason = "外部埋め込みを検出しました（HUBSPOT）。"
    assert eligible_no_form_profile(company, profile)


def test_embedded_unverified_reason_is_passed_to_profile_save(monkeypatch):
    from app.services.browser_form_analysis import save_rendered_analysis

    profile = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        form_url="https://fixture.example/contact",
        form_index=0,
        is_primary=True,
        captcha_type="CAPTCHA_NONE",
    )
    company = SimpleNamespace(id=profile.company_id, do_not_contact=False, exclusion_reason="")
    db = SimpleNamespace(get=lambda _model, _id: profile, flush=lambda: None)
    captured = {}

    monkeypatch.setattr(
        "app.services.browser_form_analysis._upsert_profile",
        lambda *_args, **kwargs: captured.update(kwargs) or profile,
    )
    monkeypatch.setattr("app.services.browser_form_analysis._log", lambda *_args, **_kwargs: None)

    result = save_rendered_analysis(
        db,
        company,
        profile.id,
        profile.form_url,
        '<html><body><script src="https://js.hsforms.net/forms/embed/v2.js"></script>'
        "</body></html>",
        1,
    )

    assert result == [profile]
    assert "外部埋め込みを検出しました" in captured["review_reason_override"]


def test_browser_analysis_preserves_known_captcha_when_rendered_dom_cannot_see_it(monkeypatch):
    from app.services.browser_form_analysis import save_rendered_analysis

    profile = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        form_url="https://fixture.example/contact",
        form_index=0,
        is_primary=True,
        captcha_type="CAPTCHA_RECAPTCHA_V3",
    )
    company = SimpleNamespace(id=profile.company_id, do_not_contact=False, exclusion_reason="")
    db = SimpleNamespace(get=lambda _model, _id: profile, flush=lambda: None)
    captured = {}

    monkeypatch.setattr(
        "app.services.browser_form_analysis._upsert_profile",
        lambda *_args, **kwargs: captured.update(kwargs) or profile,
    )
    monkeypatch.setattr("app.services.browser_form_analysis._log", lambda *_args, **_kwargs: None)

    save_rendered_analysis(
        db,
        company,
        profile.id,
        profile.form_url,
        '<html><body><form><textarea name="message"></textarea>'
        '<button type="submit">送信</button></form></body></html>',
        1,
    )

    assert captured["captcha"] == "CAPTCHA_RECAPTCHA_V3"


def test_rendered_dom_fingerprint_ignores_prefilled_values():
    template = """<!doctype html><form method="post"><textarea name="message">{value}</textarea>
    <input name="email" value="{value}"><button type="submit">送信</button></form>"""
    first = inspect_rendered_dom(
        template.format(value="sensitive one"), "https://fixture.example/contact"
    )[0]
    second = inspect_rendered_dom(
        template.format(value="sensitive two"), "https://fixture.example/contact"
    )[0]

    assert first.fingerprint == second.fingerprint


def test_rendered_analysis_request_policy_is_get_only_and_same_site():
    policy = BrowserNetworkPolicy("www.company.example")

    assert is_read_only_request("GET", "https://company.example/contact", policy)
    assert not is_read_only_request("POST", "https://company.example/contact", policy)
    assert not is_read_only_request("GET", "https://external.example/form", policy)
    assert not is_read_only_request("GET", "http://company.example/contact", policy)


def test_default_rendered_browser_analysis_setting_is_off():
    assert Settings(_env_file=None).browser_form_analysis_enabled is False


def test_site_interval_uses_a_database_advisory_lock_and_one_second_cooldown(monkeypatch):
    from browser_worker import jobs

    calls = []

    class FakeConnection:
        def execute(self, statement, params=None):
            calls.append((str(statement), params))

        def commit(self):
            calls.append(("commit", None))

        def close(self):
            calls.append(("close", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(jobs, "engine", FakeEngine())
    with _same_site_interval("www.fixture.example"):
        calls.append(("page request", None))

    sql = [statement for statement, _params in calls]
    assert "pg_advisory_lock" in sql[0]
    assert calls[0][1] == {"site_host": "fixture.example"}
    assert sql[2] == "page request"
    assert "pg_sleep(1)" in sql[3]
    assert "pg_advisory_unlock" in sql[5]


def test_dom_snapshot_redacts_fields_without_mutating_or_submitting_the_page():
    import asyncio

    from playwright.async_api import async_playwright

    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(
                '<form><input name="email" value="private@example.invalid">'
                '<textarea name="message">private text</textarea>'
                '<input type="submit" value="送信"></form>'
            )
            html = await page.evaluate(_safe_dom_script())
            current_value = await page.locator("input[name=email]").input_value()
            await browser.close()
            return html, current_value

    html, current_value = asyncio.run(scenario())
    soup = BeautifulSoup(html, "html.parser")

    assert current_value == "private@example.invalid"
    assert "private@example.invalid" not in html
    assert "private text" not in html
    assert soup.select_one('input[type="submit"]')["value"] == "送信"
