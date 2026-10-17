"""Browser navigation preflight shared with the application's robots rules."""

from __future__ import annotations

import asyncio
import base64
import ssl
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit, urlunsplit

from app.config import settings
from app.services.pinned_read_transport import TransportBlocked
from app.services.pinned_read_transport import target as validate_https_target
from app.services.robots import robots_can_fetch
from browser_worker.network_proxy import BrowserNetworkPolicy

MAX_ROBOTS_BYTES = 256_000
MAX_PAGE_NAVIGATION_SECONDS = 30


class BrowserPreflightBlocked(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class _RequiredProxyHandler(urllib.request.ProxyHandler):
    def proxy_open(self, request, proxy, proxy_type):
        original_type = request.type
        parsed_type, username, password, hostport = urllib.request._parse_proxy(proxy)
        proxy_type = parsed_type or original_type
        if username and password:
            credentials = f"{unquote(username)}:{unquote(password)}".encode("utf-8")
            encoded = base64.b64encode(credentials).decode("ascii")
            request.add_header("Proxy-authorization", f"Basic {encoded}")
        request.set_proxy(unquote(hostport), proxy_type)
        if original_type == proxy_type or original_type == "https":
            return None
        return self.parent.open(request, timeout=request.timeout)


def robots_allowed_before_navigation(
    url: str,
    policy: BrowserNetworkPolicy,
    proxy_url: str,
    *,
    user_agent: str | None = None,
    opener_factory=urllib.request.build_opener,
) -> bool:
    """Read robots through the allowlist proxy before any browser page is opened."""
    try:
        host = validate_https_target(url)
    except TransportBlocked as exc:
        raise BrowserPreflightBlocked("Only public HTTPS sites on port 443 are supported.") from exc
    if not policy.allows(host):
        raise BrowserPreflightBlocked("Target host is not allowlisted.")
    parsed = urlsplit(url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    robots_url = f"{origin}/robots.txt"
    opener = opener_factory(
        _RequiredProxyHandler({"https": proxy_url}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect(),
    )
    request = urllib.request.Request(
        robots_url,
        headers={"User-Agent": user_agent or settings.scraper_user_agent},
        method="GET",
    )
    try:
        with opener.open(request, timeout=10) as response:
            status = response.status
            body = response.read(MAX_ROBOTS_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            status, body = 404, b""
        elif exc.code in {401, 403}:
            status, body = exc.code, b""
        else:
            raise BrowserPreflightBlocked("robots.txt could not be checked.") from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise BrowserPreflightBlocked("robots.txt could not be checked.") from exc
    if len(body) > MAX_ROBOTS_BYTES:
        raise BrowserPreflightBlocked("robots.txt exceeded the size limit.")
    if status == 404:
        return True
    if status in {401, 403}:
        return False
    if status != 200:
        raise BrowserPreflightBlocked("robots.txt returned an unsupported status.")
    text = body.decode("utf-8", errors="replace")
    return robots_can_fetch(text, url, user_agent or settings.scraper_user_agent)


async def open_page_after_preflight(
    page,
    url: str,
    policy: BrowserNetworkPolicy,
    proxy_url: str,
    *,
    preflight_checker=robots_allowed_before_navigation,
):
    allowed = await asyncio.to_thread(preflight_checker, url, policy, proxy_url)
    if not allowed:
        raise BrowserPreflightBlocked("robots.txt does not allow this page.")
    return await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=MAX_PAGE_NAVIGATION_SECONDS * 1000,
    )
