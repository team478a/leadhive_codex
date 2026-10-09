"""Conservative contact extraction. Observed values are never Human confirmation."""

import json
import re
import unicodedata
from urllib.parse import unquote

from bs4 import BeautifulSoup

ASSET_SUFFIXES = {"png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "css", "js"}


def organization(soup: BeautifulSoup) -> dict:
    candidates = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            value = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph", [])
            for node in [item, *(graph if isinstance(graph, list) else [])]:
                if not isinstance(node, dict):
                    continue
                types = node.get("@type", [])
                types = [types] if isinstance(types, str) else types
                if isinstance(types, list) and any(
                    t in {"Organization", "Corporation", "LocalBusiness", "HairSalon"}
                    for t in types
                ):
                    candidates.append(node)
    # A directory with several organizations must not become its first tenant.
    return candidates[0] if len(candidates) == 1 else {}


def email(soup: BeautifulSoup, text: str) -> str:
    values = [
        unquote(str(a.get("href", "")).split(":", 1)[-1].split("?", 1)[0])
        for a in soup.select("a[href^='mailto:']")
    ]
    values.extend(re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text))
    valid = []
    for value in values:
        value = value.strip().lower()
        if len(value) > 320 or not re.fullmatch(
            r"[a-z0-9._%+\-]+@[a-z0-9](?:[a-z0-9.\-]*[a-z0-9])?\.[a-z]{2,}", value
        ):
            continue
        local, domain = value.split("@")
        if ".." in value or local.startswith(".") or local.endswith("."):
            continue
        if domain.rsplit(".", 1)[-1] in ASSET_SUFFIXES:
            continue
        valid.append(value)
    priorities = ("info@", "contact@", "inquiry@", "sales@", "support@")
    return next(
        (v for prefix in priorities for v in valid if v.startswith(prefix)),
        valid[0] if valid else "",
    )


def phone(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    number = r"(0\d{1,4}[\s()\-‐‑‒–—ー]+\d{1,4}[\s()\-‐‑‒–—ー]+\d{3,4})"
    for pattern in (r"(?:TEL|電話|Phone)\s*[:：]?\s*" + number, number):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Reject the number immediately following a FAX label.
            if re.search(
                r"(?:FAX|ファックス)\s*[:：]?\s*$",
                text[max(0, match.start() - 20) : match.start()],
                re.I,
            ):
                continue
            value = re.sub(r"[\s()‐‑‒–—ー]+", "-", match.group(1)).strip("-")
            if len(re.sub(r"\D", "", value)) in {10, 11}:
                return value
    return ""


def location_text(soup: BeautifulSoup, text: str, org: dict) -> tuple[str, str]:
    address = org.get("address")
    if isinstance(address, dict):
        value = "".join(
            str(address.get(k) or "") for k in ("addressRegion", "addressLocality", "streetAddress")
        )
        if value:
            return value, "JSON_LD_ADDRESS"
    element = soup.select_one("address")
    if element:
        return element.get_text(" ", strip=True), "ADDRESS_ELEMENT"
    # Explicit address/postcode context wins over a service-area mention.
    match = re.search(r"(?:所在地|住所|〒\s*\d{3}[-－]?\d{4})\s*[:：]?\s*(.{2,120})", text)
    if match:
        return match.group(1), "LABELLED_ADDRESS"
    if any(word in text for word in ("対応地域", "対応エリア", "サービスエリア")):
        return "", "INSUFFICIENT_ADDRESS_CONTEXT"
    return text, "TEXT_ADDRESS_CANDIDATE"
