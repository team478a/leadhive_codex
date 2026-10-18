"""Guarded browser form execution shared by real and synthetic-only tests."""

from __future__ import annotations

import asyncio
import html
import json
import re
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Page, Route, async_playwright

from app.services.browser_form_plan import BrowserFormPlan
from browser_worker import MAX_TASK_SECONDS
from browser_worker.network_proxy import AllowlistProxy, BrowserNetworkPolicy
from browser_worker.runtime import (
    _LOGIN_DETECTION_SCRIPT,
    _LOGIN_GUARD_SCRIPT,
    BrowserTaskCancelled,
    BrowserWorkerError,
    RenderedPageTask,
    _validate_rendered_task,
)
from browser_worker.safety import BrowserPreflightBlocked, open_page_after_preflight

_GUARD_SCRIPT = """
(() => {
  window.__leadhiveBlockedPopups = 0;
  window.__leadhiveBlockedDownloads = 0;
  window.open = () => { window.__leadhiveBlockedPopups += 1; return null; };
  const anchorClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function() {
    if (this.hasAttribute('download')) {
      window.__leadhiveBlockedDownloads += 1;
      return;
    }
    return anchorClick.call(this);
  };
  for (const picker of ['showOpenFilePicker', 'showSaveFilePicker', 'showDirectoryPicker']) {
    window[picker] = () => Promise.reject(
      new DOMException('File pickers are disabled.', 'AbortError')
    );
  }
})();
"""
_CAPTCHA_SCRIPT = """() => {
  const selector = [
    '[class*="captcha" i]', '[id*="captcha" i]', '[name*="captcha" i]',
    'iframe[src*="recaptcha" i]', 'iframe[src*="hcaptcha" i]',
    'iframe[src*="challenges.cloudflare.com" i]', '[class*="cf-turnstile" i]',
    '[data-sitekey]', 'input[name*="g-recaptcha-response" i]', 'script[src*="captcha" i]'
  ].join(',');
  return Boolean(document.querySelector(selector))
    || /captcha|recaptcha|hcaptcha|turnstile/i.test(document.body?.innerText || '');
}"""
_SUCCESS = re.compile(
    r"送信.{0,12}(?:完了|受付)|受け付けました|ありがとうございました|thank\s*you|message\s+has\s+been\s+sent",
    re.IGNORECASE,
)
_ERROR = re.compile(
    r"送信.{0,12}(?:失敗|できません)|入力.{0,12}(?:エラー|不備)|エラーが発生|invalid|wpcf7-not-valid-tip|has-error",
    re.IGNORECASE,
)
_CONFIRM = re.compile(r"確認|内容を確認|次へ|confirm|next", re.IGNORECASE)
_SEND = re.compile(r"送信|submit|send", re.IGNORECASE)
_BACK = re.compile(r"戻る|修正|キャンセル|back|edit", re.IGNORECASE)


@dataclass(frozen=True)
class BrowserDeliveryResult:
    status: str
    message: str
    screenshot_after: bytes | None
    response_status: int | None
    final_url: str
    confirmation_used: bool
    completion_evidence: str
    screenshot_before: bytes | None = None
    post_count: int = 0


def _same_action(candidate: str, expected: str) -> bool:
    left, right = urlsplit(candidate), urlsplit(expected)
    return (
        left.scheme == right.scheme == "https"
        and left.hostname == right.hostname
        and (left.port or 443) == (right.port or 443)
        and left.path == right.path
        and left.query == right.query
        and not left.username
        and not right.username
        and not left.password
        and not right.password
    )


async def _jpeg(page: Page) -> bytes:
    for quality in (55, 40, 28, 18, 10):
        image = await page.screenshot(
            type="jpeg", quality=quality, full_page=False, animations="disabled"
        )
        if len(image) <= 200_000:
            return image
    raise BrowserWorkerError("Screenshot could not be compressed below 200 KB.")


async def _page_text(page: Page) -> str:
    return await page.locator("body").inner_text(timeout=3000)


async def _check_page(
    page: Page, policy: BrowserNetworkPolicy, *, login_detected: asyncio.Event
) -> None:
    if login_detected.is_set() or await page.evaluate(_LOGIN_DETECTION_SCRIPT):
        raise BrowserWorkerError("Login pages are not supported.")
    if not policy.allows(urlsplit(page.url).hostname or ""):
        raise BrowserWorkerError("Browser navigation left the approved site.")
    if await page.evaluate(_CAPTCHA_SCRIPT):
        raise BrowserWorkerError("CAPTCHA forms are not supported.")
    if await page.locator("input[type=file]").count():
        raise BrowserWorkerError("File attachment fields are not supported.")


async def _field_value(locator, field) -> str:
    tag_name, input_type = await locator.evaluate(
        "element => [element.tagName.toLowerCase(), (element.type || '').toLowerCase()]"
    )
    if tag_name == "select":
        await locator.select_option(value=field.value)
        return await locator.input_value()
    if tag_name == "textarea" or (
        tag_name == "input" and input_type in {"text", "email", "tel", "url", "search", "number"}
    ):
        await locator.fill(field.value)
        return await locator.input_value()
    if tag_name == "input" and input_type in {"checkbox", "radio"}:
        should_check = bool(field.value)
        if should_check:
            await locator.check()
        elif await locator.is_checked():
            await locator.uncheck()
        return "checked" if await locator.is_checked() else ""
    raise BrowserWorkerError("Unsupported or unsafe planned form field type.")


async def _form_and_button(page: Page, plan: BrowserFormPlan, *, confirmation: bool):
    forms = page.locator("form")
    if await forms.count() <= plan.form_index:
        raise BrowserWorkerError("The approved form was not found.")
    form = forms.nth(plan.form_index)
    metadata = await form.evaluate(
        "form => ({method: (form.method || 'get').toUpperCase(), "
        "action: form.action || location.href, target: form.target || ''})"
    )
    if metadata["method"] != "POST" or not _same_action(metadata["action"], plan.action_url):
        raise BrowserWorkerError("The form method or action changed after approval.")
    if metadata["target"] and metadata["target"].casefold() not in {"_self", "_top", "_parent"}:
        raise BrowserWorkerError("Forms that open a new window are not supported.")
    controls = form.locator("button, input[type=submit], input[type=image]")
    candidates = []
    for index in range(await controls.count()):
        control = controls.nth(index)
        details = await control.evaluate(
            "element => ({type: (element.type || '').toLowerCase(), "
            "text: (element.innerText || element.value || "
            "element.getAttribute('aria-label') || '').trim()})"
        )
        if details["type"] == "reset":
            continue
        if _BACK.search(details["text"]):
            continue
        candidates.append((control, details["text"]))
    preferred = [
        control
        for control, label in candidates
        if (_SEND.search(label) if confirmation else _CONFIRM.search(label))
    ]
    if not preferred:
        preferred = [control for control, _label in candidates]
    if len(preferred) != 1:
        raise BrowserWorkerError("A unique safe form action button could not be identified.")
    return form, preferred[0]


async def _run_delivery(
    plan: BrowserFormPlan,
    *,
    mode: str,
    before_post: Callable[[bytes], bool] | None,
    cancellation_check=None,
    synthetic_fixture: str | None = None,
) -> BrowserDeliveryResult:
    if mode not in {"dry_run", "submit"}:
        raise ValueError("Unsupported browser delivery mode")
    if synthetic_fixture:
        network_policy = BrowserNetworkPolicy(site_host=urlsplit(plan.form_url).hostname)
    else:
        network_policy = _validate_rendered_task(
            RenderedPageTask(plan.form_url, urlsplit(plan.form_url).hostname or "")
        )
    if not network_policy.allows(urlsplit(plan.action_url).hostname or ""):
        raise BrowserWorkerError("Form action is outside the same-site allowlist.")

    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    login_detected = asyncio.Event()
    cancellation_detected = asyncio.Event()
    navigation_checks: set[asyncio.Task] = set()
    cancellation_monitor: asyncio.Task | None = None
    post_count = 0
    response_status: int | None = None
    begun = False
    post_authorized = False
    confirmation_ready = False
    before_image: bytes | None = None
    after_image: bytes | None = None
    confirmation_used = False
    popup_attempted = asyncio.Event()
    download_attempted = asyncio.Event()

    async with AllowlistProxy(network_policy) as proxy, async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-background-networking", "--disable-component-update",
                    "--disable-sync", "--disable-webrtc", "--disable-quic",
                    f"--proxy-server={proxy.proxy_url}", "--proxy-bypass-list=<-loopback>",
                    "--host-resolver-rules=MAP * ~NOTFOUND",
                ],
            )
            context = await browser.new_context(
                accept_downloads=False, service_workers="block", locale="ja-JP",
                viewport={"width": 1024, "height": 768},
            )
            page = await context.new_page()
            await page.add_init_script(_GUARD_SCRIPT)
            await page.add_init_script(_LOGIN_GUARD_SCRIPT)
            def on_download(download) -> None:
                download_attempted.set()
                asyncio.create_task(download.cancel())

            def on_popup(popup) -> None:
                popup_attempted.set()
                asyncio.create_task(popup.close())

            page.on("download", on_download)
            page.on("popup", on_popup)

            async def inspect_navigation(frame) -> None:
                if frame != page.main_frame:
                    return
                try:
                    if await frame.evaluate(_LOGIN_DETECTION_SCRIPT):
                        login_detected.set()
                except Exception:
                    return

            def on_frame_navigated(frame) -> None:
                check = asyncio.create_task(inspect_navigation(frame))
                navigation_checks.add(check)
                check.add_done_callback(navigation_checks.discard)

            page.on("framenavigated", on_frame_navigated)

            def record_response(response) -> None:
                nonlocal response_status
                if _same_action(response.url, plan.action_url):
                    response_status = response.status

            page.on("response", record_response)

            async def route_request(route: Route) -> None:
                nonlocal post_count, response_status, begun, before_image, post_authorized
                request = route.request
                parsed = urlsplit(request.url)
                if parsed.scheme != "https" or not network_policy.allows(parsed.hostname or ""):
                    await route.abort("blockedbyclient")
                    return
                if synthetic_fixture:
                    if request.method.upper() == "GET" and _same_action(request.url, plan.form_url):
                        await route.fulfill(
                            status=200,
                            content_type="text/html; charset=utf-8",
                            body=_fixture_html(synthetic_fixture, plan.action_url),
                        )
                        return
                    if (
                        request.method.upper() == "POST"
                        and _same_action(request.url, plan.action_url)
                    ):
                        allowed_post = post_count == 0 or (
                            plan.confirmation_expected and confirmation_ready and post_count == 1
                        )
                        if mode != "submit" or not allowed_post or not post_authorized:
                            await route.abort("blockedbyclient")
                            return
                        if not begun:
                            if before_image is None or before_post is None:
                                await route.abort("blockedbyclient")
                                return
                            if not await asyncio.to_thread(before_post, before_image):
                                await route.abort("blockedbyclient")
                                return
                            begun = True
                        post_authorized = False
                        post_count += 1
                        if synthetic_fixture == "confirmation" and post_count == 1:
                            body = (
                                '<h1>内容をご確認ください</h1><form method="post" '
                                f'action="{html.escape(plan.action_url, quote=True)}">'
                                '<input name="name" value="Synthetic Company">'
                                '<textarea name="message">Synthetic message</textarea>'
                                '<button type="submit">送信する</button></form>'
                            )
                            await route.fulfill(
                                status=200, content_type="text/html; charset=utf-8", body=body
                            )
                        elif synthetic_fixture == "error":
                            body = (
                                '<h1>入力内容にエラーがあります</h1><form method="post" '
                                f'action="{html.escape(plan.action_url, quote=True)}">'
                                '<input name="name"><textarea name="message"></textarea>'
                                '<button type="submit">送信</button></form>'
                            )
                            await route.fulfill(
                                status=200, content_type="text/html; charset=utf-8", body=body
                            )
                        elif synthetic_fixture == "no_completion":
                            await route.fulfill(
                                status=200,
                                content_type="text/html; charset=utf-8",
                                body="<h1>処理中です</h1>",
                            )
                        elif synthetic_fixture == "cf7_style":
                            await route.fulfill(
                                status=200, content_type="text/plain; charset=utf-8",
                                headers={"access-control-allow-origin": "*"},
                                body="送信が完了しました。",
                            )
                        else:
                            await route.fulfill(
                                status=200, content_type="text/html; charset=utf-8",
                                body="<h1>送信が完了しました。</h1>",
                            )
                        return
                    await route.abort("blockedbyclient")
                    return
                if request.method.upper() == "GET":
                    await route.continue_()
                    return
                allowed_post = (
                    mode == "submit"
                    and request.method.upper() == "POST"
                    and post_authorized
                    and _same_action(request.url, plan.action_url)
                    and (
                        post_count == 0
                        or plan.confirmation_expected
                        and confirmation_ready
                        and post_count == 1
                    )
                )
                if not allowed_post:
                    await route.abort("blockedbyclient")
                    return
                if not begun:
                    if before_image is None or before_post is None:
                        await route.abort("blockedbyclient")
                        return
                    if not await asyncio.to_thread(before_post, before_image):
                        await route.abort("blockedbyclient")
                        return
                    begun = True
                post_authorized = False
                post_count += 1
                await route.continue_()

            await context.route("**/*", route_request)
            await context.route_web_socket(
                "**/*", lambda socket: socket.close(code=1000, reason="websocket disabled")
            )

            async def stop_if_unsafe() -> None:
                if cancellation_detected.is_set():
                    raise BrowserTaskCancelled("Browser delivery was cancelled.")
                await _check_page(page, network_policy, login_detected=login_detected)
                if popup_attempted.is_set() or await page.evaluate(
                    "window.__leadhiveBlockedPopups || 0"
                ):
                    raise BrowserWorkerError("New-window navigation is not supported.")
                if download_attempted.is_set() or await page.evaluate(
                    "window.__leadhiveBlockedDownloads || 0"
                ):
                    raise BrowserWorkerError("Downloads are not supported.")

            async def monitor_cancellation() -> None:
                while True:
                    await asyncio.sleep(1)
                    if cancellation_check and await asyncio.to_thread(cancellation_check):
                        cancellation_detected.set()
                        if context:
                            await context.close()
                        return

            if cancellation_check:
                cancellation_monitor = asyncio.create_task(monitor_cancellation())

            if synthetic_fixture:
                page_response = await page.goto(plan.form_url, wait_until="domcontentloaded")
            else:
                page_response = await open_page_after_preflight(
                    page, plan.form_url, network_policy, proxy.proxy_url
                )
            await stop_if_unsafe()
            if page_response and page_response.status >= 400:
                raise BrowserWorkerError("Contact page returned an error status.")
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            await stop_if_unsafe()

            form, _ = await _form_and_button(page, plan, confirmation=False)
            for field in plan.fields:
                locator = page.locator(field.selector)
                if await locator.count() != 1:
                    raise BrowserWorkerError("A planned input selector did not match exactly once.")
                metadata = await locator.evaluate(
                    "element => ({name: element.name || '', "
                    "type: (element.type || element.tagName).toLowerCase(), "
                    "inside: Boolean(element.form)})"
                )
                if metadata["name"] != field.name or not metadata["inside"]:
                    raise BrowserWorkerError("A planned field identity changed after approval.")
                actual = await _field_value(locator, field)
                expected = (
                    "checked"
                    if metadata["type"] in {"checkbox", "radio"} and field.value
                    else field.value
                )
                if actual != expected:
                    raise BrowserWorkerError("Filled values did not match the approved plan.")
                await stop_if_unsafe()

            if mode == "dry_run":
                before_image = await _jpeg(page)
                if before_post is None or not await asyncio.to_thread(before_post, before_image):
                    raise BrowserWorkerError("Dry-run start could not be persisted.")
                await page.wait_for_timeout(150)
                after_image = await _jpeg(page)
                return BrowserDeliveryResult(
                    "dry_run_completed", "入力値を読み戻し、送信せずに終了しました。",
                    after_image, None, page.url, False, "dry_run_no_submit", before_image, 0,
                )

            _, initial_button = await _form_and_button(page, plan, confirmation=False)
            before_image = await _jpeg(page)
            post_authorized = True
            await initial_button.click(timeout=7000)
            await page.wait_for_timeout(1200)
            await stop_if_unsafe()
            text = await _page_text(page)
            evidence = ""
            if _SUCCESS.search(text):
                evidence = "explicit_success_text"
                status, message = "submitted", ""
            elif _ERROR.search(text):
                evidence = "explicit_error_text"
                status, message = "failed", "送信先が明示的なエラーを返しました。"
            elif plan.confirmation_expected and post_count == 1:
                _confirmation_form, final_button = await _form_and_button(
                    page, plan, confirmation=True
                )
                confirmation_ready = True
                confirmation_used = True
                post_authorized = True
                await final_button.click(timeout=7000)
                await page.wait_for_timeout(1200)
                await stop_if_unsafe()
                text = await _page_text(page)
                if _SUCCESS.search(text):
                    evidence = "explicit_success_text_after_confirmation"
                    status, message = "submitted", ""
                elif _ERROR.search(text):
                    evidence = "explicit_error_text_after_confirmation"
                    status, message = "failed", "送信先が明示的なエラーを返しました。"
                else:
                    status, message = (
                        "unknown",
                        "完了表示を確認できません。結果を確認してください。",
                    )
            else:
                status, message = (
                    "unknown",
                    "完了表示を確認できません。結果を確認してください。",
                )
            after_image = await _jpeg(page)
            if post_count == 0:
                raise BrowserWorkerError(
                    "The approved POST was not observed; submission was not started."
                )
            return BrowserDeliveryResult(
                status, message, after_image, response_status, page.url,
                confirmation_used, evidence or "no_terminal_evidence", before_image, post_count,
            )
        except BrowserPreflightBlocked as exc:
            raise BrowserWorkerError("robots.txt or network preflight blocked this page.") from exc
        except Exception as exc:
            if cancellation_detected.is_set():
                raise BrowserTaskCancelled("Browser delivery was cancelled.") from None
            if begun:
                try:
                    if page and not page.is_closed():
                        after_image = await _jpeg(page)
                except Exception:
                    pass
                return BrowserDeliveryResult(
                    "unknown", "送信後に完了状態を確認できません。結果を確認してください。",
                    after_image, response_status, page.url if page else "", confirmation_used,
                    "post_started_without_terminal_evidence", before_image, post_count,
                )
            if isinstance(exc, BrowserWorkerError):
                raise
            raise BrowserWorkerError("Browser form execution failed before a POST.") from exc
        finally:
            if cancellation_monitor:
                cancellation_monitor.cancel()
            for check in navigation_checks:
                check.cancel()
            if context:
                await context.close()
            if browser:
                await browser.close()


def run_browser_delivery_task(
    plan: BrowserFormPlan,
    *,
    mode: str,
    before_post: Callable[[bytes], bool] | None,
    cancellation_check=None,
) -> BrowserDeliveryResult:
    return asyncio.run(
        asyncio.wait_for(
            _run_delivery(
                plan,
                mode=mode,
                before_post=before_post,
                cancellation_check=cancellation_check,
            ),
            timeout=MAX_TASK_SECONDS,
        )
    )


def _fixture_html(name: str, action_url: str) -> str:
    action = html.escape(action_url, quote=True)
    form = (
        f'<form method="post" action="{action}" class="wpcf7-form">'
        '<input name="name" type="text"><textarea name="message"></textarea>'
        '<button type="submit">送信</button></form>'
    )
    if name == "javascript_rendered":
        return (
            '<div id="root">読み込み中</div><script>setTimeout(() => {'
            "document.querySelector('#root').innerHTML = "
            + json.dumps(form, ensure_ascii=False)
            + ";}, 100);</script>"
        )
    if name == "cf7_style":
        return (
            '<div class="wpcf7"><form method="post" action="'
            + action
            + '" class="wpcf7-form"><input name="name" type="text">'
            '<textarea name="message"></textarea><button type="button" id="send">送信</button>'
            '<output id="result"></output></form></div><script>'
            "document.querySelector('#send').addEventListener('click', async () => {"
            "const response = await fetch('"
            + action
            + "', {method:'POST', body:new FormData(document.querySelector('form'))});"
            "document.querySelector('#result').textContent = await response.text();});</script>"
        )
    if name == "confirmation":
        return (
            f'<h1>内容をご確認ください</h1><form method="post" action="{action}">'
            '<input name="name" type="text"><textarea name="message"></textarea>'
            '<button type="submit">確認して送信</button></form>'
        )
    return form


def run_synthetic_delivery_task(fixture: str, *, mode: str = "submit") -> BrowserDeliveryResult:
    """Execute only a packaged fixture; fixture requests are fulfilled locally in Playwright."""
    if fixture not in {
        "normal", "cf7_style", "confirmation", "javascript_rendered", "error", "no_completion"
    }:
        raise BrowserWorkerError("Unknown packaged synthetic delivery fixture.")
    from app.services.browser_form_plan import BrowserFormFieldPlan

    action_url = "https://fixture.invalid/submit"
    plan = BrowserFormPlan(
        project_id=uuid.uuid4(), company_id=uuid.uuid4(), source_draft_id=uuid.uuid4(),
        form_profile_id=uuid.uuid4(), form_fingerprint="0" * 64,
        form_url="https://fixture.invalid/contact", action_url=action_url, form_index=0,
        confirmation_expected=fixture == "confirmation",
        submission_kind="contact_form_7" if fixture == "cf7_style" else "native",
        fields=(
            BrowserFormFieldPlan(
                profile_field_id=uuid.uuid4(), selector="input[name='name']", name="name",
                field_type="text", mapped_key="company_name", value="Synthetic Company",
            ),
            BrowserFormFieldPlan(
                profile_field_id=uuid.uuid4(), selector="textarea[name='message']", name="message",
                field_type="textarea", mapped_key="message", value="Synthetic message",
            ),
        ),
    )
    return asyncio.run(
        asyncio.wait_for(
            _run_delivery(
                plan, mode=mode, before_post=lambda _image: True, synthetic_fixture=fixture,
            ),
            timeout=MAX_TASK_SECONDS,
        )
    )
