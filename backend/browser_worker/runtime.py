import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Mapping
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, async_playwright

from browser_worker import MAX_TASK_SECONDS
from browser_worker.network_proxy import AllowlistProxy, BrowserNetworkPolicy
from browser_worker.safety import BrowserPreflightBlocked, open_page_after_preflight

logger = logging.getLogger("leadhive.browser_worker")
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_NAMES = frozenset(
    {
        "normal",
        "cf7_style",
        "confirmation",
        "javascript_rendered",
        "blocked_submit",
        "network_probe",
        "file_input",
        "popup_probe",
        "file_chooser_probe",
        "download_probe",
        "login_navigation",
    }
)
MAX_FIELDS = 100
MAX_VALUE_CHARS = 4000
MAX_SELECTOR_CHARS = 300
_TASK_LOCK = Lock()

_SAFE_SCRIPT = """
(() => {
  window.__leadhiveBlockedSubmits = 0;
  window.__leadhiveBlockedPopups = 0;
  window.__leadhiveBlockedFileChoosers = 0;
  window.__leadhiveBlockedDownloads = 0;
  window.open = () => { window.__leadhiveBlockedPopups += 1; return null; };
  const inputClick = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function() {
    if (this.type === 'file') {
      window.__leadhiveBlockedFileChoosers += 1;
      return;
    }
    return inputClick.call(this);
  };
  if (HTMLInputElement.prototype.showPicker) {
    HTMLInputElement.prototype.showPicker = function() {
      if (this.type === 'file') {
        window.__leadhiveBlockedFileChoosers += 1;
        return;
      }
    };
  }
  document.addEventListener('click', event => {
    let input = event.target;
    if (input instanceof HTMLLabelElement && input.htmlFor) {
      input = document.getElementById(input.htmlFor);
    }
    if (input instanceof HTMLInputElement && input.type === 'file') {
      window.__leadhiveBlockedFileChoosers += 1;
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  for (const picker of ['showOpenFilePicker', 'showSaveFilePicker', 'showDirectoryPicker']) {
    window[picker] = () => {
      window.__leadhiveBlockedFileChoosers += 1;
      return Promise.reject(new DOMException('File pickers are disabled.', 'AbortError'));
    };
  }
  const anchorClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function() {
    if (this.hasAttribute('download')) {
      window.__leadhiveBlockedDownloads += 1;
      return;
    }
    return anchorClick.call(this);
  };
  document.addEventListener('submit', event => {
    window.__leadhiveBlockedSubmits += 1;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  const blockSubmit = function() {
    window.__leadhiveBlockedSubmits += 1;
  };
  HTMLFormElement.prototype.submit = blockSubmit;
  HTMLFormElement.prototype.requestSubmit = blockSubmit;
})();
"""

_LOGIN_DETECTION_SCRIPT = """() => {
  const path = location.pathname || '';
  const password = document.querySelector(
    'input[type="password"], input[autocomplete="current-password"]'
  );
  const loginText = /ログイン|サインイン|sign\\s?in|log\\s?in/i;
  const title = document.title || '';
  const headings = Array.from(document.querySelectorAll('h1, h2, [role="heading"]'))
    .map(element => element.innerText || '');
  const loginForm = Array.from(document.forms).some(form => loginText.test(form.innerText || ''));
  return Boolean(window.__leadhiveLoginDetected)
    || Boolean(password)
    || loginText.test(title)
    || headings.some(text => loginText.test(text))
    || loginForm
    || /(?:^|\\/)(?:login|log-in|signin|sign-in)(?:\\/|$)/i.test(path);
}"""

_LOGIN_GUARD_SCRIPT = """
(() => {
  const inspect = () => {
    const loginText = /ログイン|サインイン|sign\\s?in|log\\s?in/i;
    const password = document.querySelector(
      'input[type="password"], input[autocomplete="current-password"]'
    );
    const headings = Array.from(document.querySelectorAll('h1, h2, [role="heading"]'))
      .map(element => element.innerText || '');
    const loginForm = Array.from(document.forms).some(form => loginText.test(form.innerText || ''));
    if (password || loginText.test(document.title || '')
        || headings.some(text => loginText.test(text)) || loginForm
        || /(?:^|\\/)(?:login|log-in|signin|sign-in)(?:\\/|$)/i.test(location.pathname || '')) {
      window.__leadhiveLoginDetected = true;
    }
  };
  new MutationObserver(inspect).observe(document, {
    subtree: true, childList: true, attributes: true, characterData: true
  });
  document.addEventListener('DOMContentLoaded', inspect);
  window.addEventListener('pageshow', inspect);
})();
"""


class BrowserWorkerError(RuntimeError):
    pass


class SubmissionBlockedError(BrowserWorkerError):
    pass


class ConcurrentBrowserTaskError(BrowserWorkerError):
    pass


class BrowserTaskCancelled(BrowserWorkerError):
    pass


@dataclass(frozen=True)
class SyntheticFormTask:
    fixture: str
    fields: Mapping[str, str]


@dataclass(frozen=True)
class RenderedPageTask:
    url: str
    site_host: str


@dataclass(frozen=True)
class FillResult:
    fixture: str
    values: dict[str, str]
    blocked_request_count: int
    blocked_websocket_count: int
    blocked_popup_count: int
    blocked_file_chooser_count: int
    blocked_download_count: int


@dataclass(frozen=True)
class RenderedPageResult:
    final_url: str
    html: str
    blocked_non_get_count: int


def _validate_rendered_task(task: RenderedPageTask) -> BrowserNetworkPolicy:
    from app.services.pinned_read_transport import TransportBlocked, target

    try:
        site_host = target(f"https://{task.site_host}/")
        target_host = target(task.url)
        parsed = urlsplit(task.url)
    except (TransportBlocked, TypeError, ValueError) as exc:
        raise BrowserWorkerError("Only public HTTPS pages can be analyzed.") from exc
    policy = BrowserNetworkPolicy(site_host)
    if (
        not policy.allows(target_host)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise BrowserWorkerError("The analysis URL is outside its approved site host.")
    return policy


def _safe_dom_script() -> str:
    return """() => {
      const root = document.documentElement.cloneNode(true);
      for (const field of root.querySelectorAll('input, textarea, select')) {
        if (!['submit', 'button', 'reset'].includes((field.type || '').toLowerCase())) {
          field.removeAttribute('value');
        }
        if (field instanceof HTMLTextAreaElement) field.textContent = '';
        for (const option of field.querySelectorAll('option[selected]')) {
          option.removeAttribute('selected');
        }
      }
      return '<!doctype html>' + root.outerHTML;
    }"""


def is_read_only_request(method: str, url: str, policy: BrowserNetworkPolicy) -> bool:
    parsed = urlsplit(url)
    return (
        method.upper() == "GET"
        and parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and policy.allows(parsed.hostname or "")
    )


def _validate_task(task: SyntheticFormTask) -> str:
    if task.fixture not in FIXTURE_NAMES:
        raise BrowserWorkerError("Only packaged synthetic fixtures can be opened.")
    if len(task.fields) > MAX_FIELDS:
        raise BrowserWorkerError("Too many fields in browser task.")
    for selector, value in task.fields.items():
        if not selector or len(selector) > MAX_SELECTOR_CHARS or len(value) > MAX_VALUE_CHARS:
            raise BrowserWorkerError("Browser task field exceeds its size limit.")
    fixture_path = FIXTURE_DIR / f"{task.fixture}.html"
    if fixture_path.parent != FIXTURE_DIR or not fixture_path.is_file():
        raise BrowserWorkerError("Synthetic fixture is unavailable.")
    return fixture_path.read_text(encoding="utf-8")


def _install_submission_guard(html: str) -> str:
    guard_script = f"<script>{_SAFE_SCRIPT}</script>"
    doctype = re.match(r"\s*<!doctype\s+html[^>]*>", html, flags=re.IGNORECASE)
    if doctype:
        return html[: doctype.end()] + guard_script + html[doctype.end() :]
    return "<!doctype html>" + guard_script + html


async def _fill_task(
    task: SyntheticFormTask,
    html: str,
    *,
    network_policy: BrowserNetworkPolicy,
    cancellation_check=None,
) -> FillResult:
    blocked_requests: list[str] = []
    blocked_websockets: list[str] = []
    browser: Browser | None = None
    context: BrowserContext | None = None
    navigation_checks: set[asyncio.Task] = set()
    login_detected = asyncio.Event()
    cancellation_detected = asyncio.Event()
    cancellation_monitor: asyncio.Task | None = None

    async def block_request(route) -> None:
        blocked_requests.append(route.request.url)
        await route.abort("blockedbyclient")

    async def block_websocket(websocket_route) -> None:
        blocked_websockets.append(websocket_route.url)
        await websocket_route.close(code=1000, reason="offline synthetic worker")

    async with AllowlistProxy(network_policy) as proxy, async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-sync",
                    "--disable-webrtc",
                    "--disable-quic",
                    f"--proxy-server={proxy.proxy_url}",
                    "--proxy-bypass-list=<-loopback>",
                    "--host-resolver-rules=MAP * ~NOTFOUND",
                ],
            )
            context = await browser.new_context(
                accept_downloads=False,
                service_workers="block",
                locale="ja-JP",
            )
            await context.route("**/*", block_request)
            await context.route_web_socket("**/*", block_websocket)
            page = await context.new_page()
            page.on("download", lambda download: asyncio.create_task(download.cancel()))
            page.on("popup", lambda popup: asyncio.create_task(popup.close()))

            async def inspect_navigation(frame) -> None:
                if frame != page.main_frame:
                    return
                try:
                    found = await frame.evaluate(_LOGIN_DETECTION_SCRIPT)
                except Exception:
                    return
                if found:
                    login_detected.set()

            def on_frame_navigated(frame) -> None:
                check = asyncio.create_task(inspect_navigation(frame))
                navigation_checks.add(check)
                check.add_done_callback(navigation_checks.discard)

            page.on("framenavigated", on_frame_navigated)

            async def stop_if_unsafe() -> None:
                if cancellation_detected.is_set():
                    raise BrowserTaskCancelled("Browser analysis job was cancelled.")
                if login_detected.is_set():
                    raise BrowserWorkerError("Login pages are not supported.")
                if await page.evaluate(_LOGIN_DETECTION_SCRIPT):
                    raise BrowserWorkerError("Login pages are not supported.")

            async def monitor_cancellation() -> None:
                while True:
                    await asyncio.sleep(1)
                    if cancellation_check is not None and await asyncio.to_thread(
                        cancellation_check
                    ):
                        cancellation_detected.set()
                        if context is not None:
                            await context.close()
                        return

            if cancellation_check is not None:
                cancellation_monitor = asyncio.create_task(monitor_cancellation())

            await page.add_init_script(_SAFE_SCRIPT)
            await page.add_init_script(_LOGIN_GUARD_SCRIPT)
            await page.set_content(
                _install_submission_guard(html),
                wait_until="load",
                timeout=MAX_TASK_SECONDS * 1000,
            )
            if task.fixture == "login_navigation":
                await page.wait_for_timeout(100)

            await stop_if_unsafe()

            values: dict[str, str] = {}
            for selector, value in task.fields.items():
                await stop_if_unsafe()
                locator = page.locator(selector)
                if await locator.count() != 1:
                    raise BrowserWorkerError("Each field selector must match exactly once.")
                metadata = await locator.evaluate(
                    "element => ({tag: element.tagName.toLowerCase(), "
                    "type: (element.type || '').toLowerCase()})"
                )
                tag_name = metadata["tag"]
                input_type = metadata["type"]
                if tag_name == "select":
                    await locator.select_option(value=value)
                elif tag_name == "textarea" or (
                    tag_name == "input"
                    and input_type in {"text", "email", "tel", "url", "search", "number"}
                ):
                    await locator.fill(value)
                else:
                    raise BrowserWorkerError("Unsupported or unsafe form field type.")
                actual = await locator.input_value()
                if actual != value:
                    raise BrowserWorkerError("Filled value did not match the approved value.")
                values[selector] = actual
                await stop_if_unsafe()

            blocked_submit_count = await page.evaluate("window.__leadhiveBlockedSubmits || 0")
            if blocked_submit_count:
                raise SubmissionBlockedError(
                    "A synthetic form attempted to submit; it was blocked."
                )
            blocked_popup_count = await page.evaluate("window.__leadhiveBlockedPopups || 0")
            blocked_file_chooser_count = await page.evaluate(
                "window.__leadhiveBlockedFileChoosers || 0"
            )
            blocked_download_count = await page.evaluate("window.__leadhiveBlockedDownloads || 0")
            return FillResult(
                fixture=task.fixture,
                values=values,
                blocked_request_count=len(blocked_requests),
                blocked_websocket_count=len(blocked_websockets),
                blocked_popup_count=blocked_popup_count,
                blocked_file_chooser_count=blocked_file_chooser_count,
                blocked_download_count=blocked_download_count,
            )
        except Exception:
            if cancellation_detected.is_set():
                raise BrowserTaskCancelled("Browser analysis job was cancelled.") from None
            raise
        finally:
            if cancellation_monitor is not None:
                cancellation_monitor.cancel()
            for check in navigation_checks:
                check.cancel()
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()


def run_synthetic_task(
    task: SyntheticFormTask,
    *,
    network_policy: BrowserNetworkPolicy | None = None,
    cancellation_check=None,
) -> FillResult:
    html = _validate_task(task)
    if not _TASK_LOCK.acquire(blocking=False):
        raise ConcurrentBrowserTaskError("Only one browser job may run at a time.")
    try:
        return asyncio.run(
            asyncio.wait_for(
                _fill_task(
                    task,
                    html,
                    network_policy=network_policy or BrowserNetworkPolicy(),
                    cancellation_check=cancellation_check,
                ),
                timeout=MAX_TASK_SECONDS,
            )
        )
    except TimeoutError as exc:
        raise BrowserWorkerError("Browser task exceeded the 90-second limit.") from exc
    finally:
        _TASK_LOCK.release()


async def _render_page_task(
    task: RenderedPageTask,
    *,
    network_policy: BrowserNetworkPolicy,
    cancellation_check=None,
) -> RenderedPageResult:
    blocked_requests: list[str] = []
    browser: Browser | None = None
    context: BrowserContext | None = None
    navigation_checks: set[asyncio.Task] = set()
    login_detected = asyncio.Event()
    cancellation_detected = asyncio.Event()
    cancellation_monitor: asyncio.Task | None = None

    async def route_read_only_request(route) -> None:
        request = route.request
        if not is_read_only_request(request.method, request.url, network_policy):
            blocked_requests.append(request.url)
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def block_websocket(websocket_route) -> None:
        await websocket_route.close(code=1000, reason="browser analysis does not use websockets")

    async with AllowlistProxy(network_policy) as proxy, async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-sync",
                    "--disable-webrtc",
                    "--disable-quic",
                    f"--proxy-server={proxy.proxy_url}",
                    "--proxy-bypass-list=<-loopback>",
                    "--host-resolver-rules=MAP * ~NOTFOUND",
                ],
            )
            context = await browser.new_context(
                accept_downloads=False,
                service_workers="block",
                locale="ja-JP",
            )
            await context.route("**/*", route_read_only_request)
            await context.route_web_socket("**/*", block_websocket)
            page = await context.new_page()
            page.on("download", lambda download: asyncio.create_task(download.cancel()))
            page.on("popup", lambda popup: asyncio.create_task(popup.close()))

            async def inspect_navigation(frame) -> None:
                if frame != page.main_frame:
                    return
                try:
                    found = await frame.evaluate(_LOGIN_DETECTION_SCRIPT)
                except Exception:
                    return
                if found:
                    login_detected.set()

            def on_frame_navigated(frame) -> None:
                check = asyncio.create_task(inspect_navigation(frame))
                navigation_checks.add(check)
                check.add_done_callback(navigation_checks.discard)

            page.on("framenavigated", on_frame_navigated)

            async def stop_if_unsafe() -> None:
                if cancellation_detected.is_set():
                    raise BrowserTaskCancelled("Browser analysis job was cancelled.")
                if login_detected.is_set() or await page.evaluate(_LOGIN_DETECTION_SCRIPT):
                    raise BrowserWorkerError("Login pages are not supported.")

            async def monitor_cancellation() -> None:
                while True:
                    await asyncio.sleep(1)
                    if cancellation_check is not None and await asyncio.to_thread(
                        cancellation_check
                    ):
                        cancellation_detected.set()
                        if context is not None:
                            await context.close()
                        return

            if cancellation_check is not None:
                cancellation_monitor = asyncio.create_task(monitor_cancellation())

            await page.add_init_script(_SAFE_SCRIPT)
            await page.add_init_script(_LOGIN_GUARD_SCRIPT)
            response = await open_page_after_preflight(
                page,
                task.url,
                network_policy,
                proxy.proxy_url,
            )
            await stop_if_unsafe()
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await page.wait_for_timeout(500)
            await stop_if_unsafe()
            final_url = page.url
            final_policy = _validate_rendered_task(RenderedPageTask(final_url, task.site_host))
            if final_policy.site_host != network_policy.site_host:
                raise BrowserWorkerError("Navigation left the approved site host.")
            if response is not None and response.status >= 400:
                raise BrowserWorkerError("The contact page returned an error status.")
            if await page.evaluate("window.__leadhiveBlockedSubmits || 0"):
                raise SubmissionBlockedError("A page attempted to submit a form; it was blocked.")
            html = await page.evaluate(_safe_dom_script())
            if len(html.encode("utf-8")) > 2_000_000:
                raise BrowserWorkerError("Rendered DOM exceeded the size limit.")
            return RenderedPageResult(
                final_url=final_url,
                html=html,
                blocked_non_get_count=len(blocked_requests),
            )
        except BrowserPreflightBlocked as exc:
            raise BrowserWorkerError("robots.txt or network preflight blocked this page.") from exc
        except Exception:
            if cancellation_detected.is_set():
                raise BrowserTaskCancelled("Browser analysis job was cancelled.") from None
            raise
        finally:
            if cancellation_monitor is not None:
                cancellation_monitor.cancel()
            for check in navigation_checks:
                check.cancel()
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()


def run_rendered_page_task(
    task: RenderedPageTask,
    *,
    network_policy: BrowserNetworkPolicy | None = None,
    cancellation_check=None,
) -> RenderedPageResult:
    policy = _validate_rendered_task(task)
    if network_policy is not None and network_policy != policy:
        raise BrowserWorkerError("A rendered page task must use its own same-site policy.")
    if not _TASK_LOCK.acquire(blocking=False):
        raise ConcurrentBrowserTaskError("Only one browser job may run at a time.")
    try:
        return asyncio.run(
            asyncio.wait_for(
                _render_page_task(
                    task,
                    network_policy=policy,
                    cancellation_check=cancellation_check,
                ),
                timeout=MAX_TASK_SECONDS,
            )
        )
    except TimeoutError as exc:
        raise BrowserWorkerError("Browser page analysis exceeded the 90-second limit.") from exc
    finally:
        _TASK_LOCK.release()
