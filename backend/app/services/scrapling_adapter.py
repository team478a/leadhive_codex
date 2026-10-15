"""Opt-in, read-only experiment. No worker, database or delivery integration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Literal

from app.config import settings
from app.services.scraper import FetchedPage, PageData, SafeFetcher, ScrapeError, extract_page

Mode = Literal["scrapling_static", "scrapling_dynamic_replay"]


class ProbeUnavailable(ValueError):
    """Only a fixed, non-sensitive reason code may leave the experiment."""


@dataclass
class ProbeResult:
    method: str
    data: PageData | None
    elapsed_seconds: float
    failure_reason: str | None = None
    blocked_browser_requests: int = 0


def enabled() -> None:
    if not settings.scrapling_probe_enabled:
        raise ProbeUnavailable("SCRAPLING_PROBE_DISABLED")


def acquire(url: str) -> tuple[FetchedPage, float, int]:
    """Keep the existing robots, redirect, size, rate and public-URL checks."""
    enabled()
    started = time.monotonic()

    class LimitedFetcher(SafeFetcher):
        def _request(self, *args, **kwargs):
            if self._request_count >= 8:
                raise ScrapeError("検証用GET上限に達しました。")
            return super()._request(*args, **kwargs)

    fetcher = LimitedFetcher()
    try:
        page = fetcher.fetch_html(url)
        return page, time.monotonic() - started, fetcher._request_count
    except Exception as exc:
        setattr(exc, "probe_external_gets", fetcher._request_count)
        setattr(exc, "probe_elapsed_seconds", time.monotonic() - started)
        raise
    finally:
        fetcher.close()


def render_offline(page: FetchedPage) -> tuple[str, int]:
    """Scrapling browser sees acquired bytes only, never direct website traffic."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "PATH",
            "LOCALAPPDATA",
            "HOME",
            "USERPROFILE",
            "PLAYWRIGHT_BROWSERS_PATH",
            "PYTHONPATH",
        }
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "app.services.scrapling_render_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=os.name != "nt",
    )
    try:
        output, _ = process.communicate(
            json.dumps({"url": page.url, "html": page.html}).encode(), timeout=20
        )
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            import signal

            getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
        process.kill()
        process.communicate()
        raise ProbeUnavailable("RENDER_TIMEOUT") from None
    if process.returncode or len(output) > settings.scraper_max_bytes * 2:
        raise ProbeUnavailable("RENDER_FAILED")
    try:
        result = json.loads(output)
        html = result["html"]
        blocked = result["blocked_requests"]
        if not isinstance(html, str) or not isinstance(blocked, int):
            raise ValueError
        return html, blocked
    except (ValueError, KeyError, TypeError):
        raise ProbeUnavailable("RENDER_FAILED") from None


def probe(page: FetchedPage, mode: Mode) -> ProbeResult:
    enabled()
    started = time.monotonic()
    try:
        if len(page.html.encode()) > settings.scraper_max_bytes:
            raise ProbeUnavailable("INPUT_TOO_LARGE")
        if mode == "scrapling_static":
            from scrapling import Selector

            html = str(Selector(page.html, adaptive=False, huge_tree=False).get())
            blocked = 0
        elif mode == "scrapling_dynamic_replay":
            html, blocked = render_offline(page)
        else:
            raise ProbeUnavailable("UNKNOWN_MODE")
        data = extract_page(html, page.url)
        data.scraped_urls = [page.url]
        return ProbeResult(mode, data, time.monotonic() - started, blocked_browser_requests=blocked)
    except ImportError:
        reason = "OPTIONAL_DEPENDENCY_MISSING"
    except ProbeUnavailable as exc:
        reason = str(exc)
    except Exception:
        reason = "EXTRACTION_FAILED"
    return ProbeResult(mode, None, time.monotonic() - started, reason)


def acquisition_failure(exc: Exception) -> str:
    if not isinstance(exc, ScrapeError):
        return "ACQUISITION_UNKNOWN"
    text = exc.public_message
    if "robots" in text:
        return "ROBOTS_BLOCKED_OR_UNAVAILABLE"
    if any(value in text for value in ("URL", "プライベート", "標準ポート", "転送")):
        return "TARGET_SAFETY_REJECTED"
    return "HTTP_ACQUISITION_FAILED"
