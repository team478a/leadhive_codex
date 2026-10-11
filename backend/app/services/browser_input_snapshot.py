"""Explicit, bounded GET acquisition for a private input-only browser bundle.

No database, AI, approval or dispatch imports. Browser rendering never fetches live.
"""

import hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.services.form_intelligence.rules import sales_contact_status
from app.services.scraper import SafeFetcher, ScrapeError, validate_public_url
from app.services.static_form_diagnostics import diagnose_static_form

MAX_RESOURCES = 8
MAX_BUNDLE_BYTES = 2_000_000


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def acquire_snapshot(
    url: str, *, terms_confirmed: bool, resource_urls: list[str] | None = None
) -> dict:
    if resource_urls is not None and (
        len(resource_urls) > MAX_RESOURCES
        or any(not isinstance(value, str) for value in resource_urls)
        or len(set(resource_urls)) != len(resource_urls)
    ):
        raise ScrapeError("描画リソースの選択が不正です。")
    if terms_confirmed is not True:
        raise ScrapeError("利用条件の確認が必要です。")
    target = validate_public_url(url)
    if urlsplit(target).scheme != "https":
        raise ScrapeError("HTTPSの公開フォームURLのみ取得できます。")
    fetcher = SafeFetcher()
    # Constrain even the initial redirect to this company site.
    fetcher.site_root = target
    started = datetime.now(timezone.utc).isoformat()
    try:
        page = fetcher.fetch_html(target)
        soup = BeautifulSoup(page.html, "html.parser")
        permission, evidence = sales_contact_status(soup.get_text(" ", strip=True), False)
        if permission == "PROHIBITED":
            return {
                "definition": "rendered-input-acquisition-v1",
                "status": "BLOCKED",
                "reason": "SALES_PROHIBITED",
                "observedAt": started,
                "getRequests": fetcher._request_count,
                "prohibitionEvidence": evidence,
                "bundle": None,
            }
        if len(page.html.encode("utf-8")) > 500_000:
            raise ScrapeError("保存HTMLのサイズ上限を超えました。")
        origin = urlsplit(page.url)
        urls: dict[str, str] = {}
        base = page.url
        base_element = soup.select_one("base[href]")
        if base_element:
            base = urljoin(base, str(base_element.get("href")))
        for node in soup.select("script[src], link[rel~='stylesheet'][href]"):
            candidate = urljoin(base, str(node.get("src") or node.get("href")))
            parts = urlsplit(candidate)
            candidate = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
            if (
                (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc)
                or parts.username
                or parts.password
            ):
                # Third-party resources are not fetched. Rendering will fail closed
                # if they are required; do not substitute a successful input label.
                continue
            urls[candidate] = "script" if node.name == "script" else "style"
        inventory = [{"url": value, "kind": kind} for value, kind in urls.items()]
        if resource_urls is not None:
            if any(value not in urls for value in resource_urls):
                raise ScrapeError("ページにない、または別サイトのリソースは選択できません。")
            # Preserve document order; selection is not permission to execute or send.
            selected = {value: kind for value, kind in urls.items() if value in resource_urls}
        else:
            selected = urls
        if len(selected) > MAX_RESOURCES:
            return {
                "definition": "rendered-input-acquisition-v1",
                "status": "RESOURCE_REVIEW_REQUIRED",
                "reason": "RESOURCE_LIMIT",
                "observedAt": started,
                "getRequests": fetcher._request_count,
                "resourceInventory": inventory,
                "fieldDiagnostics": diagnose_static_form(page.html),
                "pageSnapshot": {
                    "html": page.html,
                    "expectedHtmlHash": _sha(page.html),
                    "sourceUrl": page.url,
                },
                "bundle": None,
            }
        resources = []
        size = len(page.html.encode("utf-8"))
        for resource_url, kind in selected.items():
            asset = fetcher.fetch_browser_resource(resource_url, kind)
            if asset.url != resource_url:
                raise ScrapeError("描画リソースの転送は未対応です。")
            size += len(asset.html.encode("utf-8"))
            if size > MAX_BUNDLE_BYTES:
                raise ScrapeError("描画用Snapshotの合計サイズ上限を超えました。")
            resources.append(
                {
                    "url": resource_url,
                    "kind": kind,
                    "body": asset.html,
                    "sha256": _sha(asset.html),
                }
            )
        return {
            "definition": "rendered-input-acquisition-v1",
            "status": "SNAPSHOT_READY",
            "observedAt": started,
            "getRequests": fetcher._request_count,
            "resourceInventory": inventory,
            "fieldDiagnostics": diagnose_static_form(page.html),
            "omittedResourceCount": len(urls) - len(selected),
            "bundle": {
                "html": page.html,
                "expectedHtmlHash": _sha(page.html),
                "sourceUrl": page.url,
                "permission": "UNKNOWN",
                "resources": resources,
            },
        }
    finally:
        fetcher.close()
