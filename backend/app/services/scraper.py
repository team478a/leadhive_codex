import ipaddress
import json
import logging
import re
import socket
import urllib.robotparser
from dataclasses import dataclass
from html import unescape
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.collection import canonicalize_url

logger = logging.getLogger("leadhive")

PREFECTURES = (
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
)

AGGREGATOR_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
    "linkedin.com",
    "wikipedia.org",
    "itp.ne.jp",
    "townpage.goo.ne.jp",
    "mapion.co.jp",
}

CONTACT_HINTS = (
    "contact",
    "inquiry",
    "inquire",
    "form",
    "otoiawase",
    "toiawase",
    "お問い合わせ",
    "お問合せ",
    "ご相談",
)
IMPORTANT_PAGE_HINTS = (
    (100, CONTACT_HINTS),
    (80, ("company", "corporate", "profile", "about", "会社概要", "企業情報")),
    (60, ("service", "business", "solution", "事業", "サービス")),
    (40, ("recruit", "career", "採用", "求人")),
)
MAX_SECONDARY_PAGES = 4


class ScrapeError(Exception):
    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


@dataclass
class FetchedPage:
    url: str
    html: str


@dataclass
class PageData:
    company_name: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    prefecture: str = ""
    city: str = ""
    contact_url: str = ""
    instagram_url: str = ""
    x_url: str = ""
    tiktok_url: str = ""
    facebook_url: str = ""
    youtube_url: str = ""
    line_url: str = ""
    business_summary: str = ""
    website_text: str = ""
    scraped_urls: list[str] | None = None


def is_aggregator_domain(domain: str) -> bool:
    normalized = domain.lower().removeprefix("www.")
    return any(normalized == item or normalized.endswith("." + item) for item in AGGREGATOR_DOMAINS)


def _validated_target(url: str) -> tuple[str, str]:
    raw_parsed = urlsplit(url.strip())
    if raw_parsed.username or raw_parsed.password:
        raise ScrapeError("認証情報を含むURLは解析できません。")
    canonical, _ = canonicalize_url(url)
    canonical_parsed = urlsplit(canonical)
    normalized = urlunsplit(
        (
            canonical_parsed.scheme,
            canonical_parsed.netloc,
            raw_parsed.path,
            raw_parsed.query,
            "",
        )
    )
    parsed = urlsplit(normalized)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ScrapeError("URLのポートが正しくありません。") from exc
    if port not in (None, 80, 443):
        raise ScrapeError("標準ポート以外のURLは解析できません。")
    hostname = parsed.hostname or ""
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                hostname, port or (443 if parsed.scheme == "https" else 80)
            )
        }
    except socket.gaierror as exc:
        raise ScrapeError("Webサイトのアドレスを解決できません。") from exc
    if not addresses:
        raise ScrapeError("Webサイトのアドレスを解決できません。")
    for address in addresses:
        try:
            if not ipaddress.ip_address(address).is_global:
                raise ScrapeError("プライベートネットワークのURLは解析できません。")
        except ValueError as exc:
            raise ScrapeError("Webサイトのアドレスが正しくありません。") from exc
    return normalized, hostname


def validate_public_url(url: str) -> str:
    """Return a normalized public URL after applying the scraper's SSRF checks."""
    return _validated_target(url)[0]


class SafeFetcher:
    def __init__(self):
        self.client = httpx.Client(
            timeout=settings.scraper_timeout_seconds,
            follow_redirects=False,
            headers={
                "User-Agent": settings.scraper_user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def close(self):
        self.client.close()

    def _request(
        self, url: str, max_bytes: int, redirects: int = 0, robots_request: bool = False
    ) -> FetchedPage:
        if redirects > 5:
            raise ScrapeError("リダイレクト回数が上限を超えました。")
        normalized, _ = _validated_target(url)
        try:
            with self.client.stream("GET", normalized) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ScrapeError("Webサイトのリダイレクト先が不明です。")
                    return self._request(
                        urljoin(normalized, location), max_bytes, redirects + 1, robots_request
                    )
                if robots_request and response.status_code == 404:
                    return FetchedPage(str(response.url), "")
                if robots_request and response.status_code in {401, 403}:
                    return FetchedPage(str(response.url), "User-agent: *\nDisallow: /")
                if response.status_code >= 400:
                    raise ScrapeError(
                        f"Webサイトを取得できませんでした（HTTP {response.status_code}）。"
                    )
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type and "text/plain" not in content_type:
                    raise ScrapeError("HTMLではないコンテンツは解析できません。")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ScrapeError("Webサイトのデータサイズが上限を超えました。")
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ScrapeError("Webサイトのデータサイズが上限を超えました。")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                return FetchedPage(
                    str(response.url), b"".join(chunks).decode(encoding, errors="replace")
                )
        except ScrapeError:
            raise
        except httpx.HTTPError as exc:
            raise ScrapeError("Webサイトへの接続に失敗しました。") from exc

    def robots_allowed(self, url: str) -> bool:
        parsed = urlsplit(url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        cached = getattr(self, "_robots", {}).get(origin)
        if cached:
            return cached.can_fetch(settings.scraper_user_agent, url)
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        try:
            page = self._request(robots_url, 256_000, robots_request=True)
        except ScrapeError:
            return False
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(page.html.splitlines())
        if not hasattr(self, "_robots"):
            self._robots = {}
        self._robots[origin] = parser
        return parser.can_fetch(settings.scraper_user_agent, url)

    def fetch_html(self, url: str) -> FetchedPage:
        normalized, _ = _validated_target(url)
        if not self.robots_allowed(normalized):
            raise ScrapeError("robots.txtにより解析が許可されていません。")
        return self._request(normalized, settings.scraper_max_bytes)


def _clean_url(value: str, base_url: str) -> str:
    absolute = urljoin(base_url, unescape(value.strip()))
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _extract_company_name(soup: BeautifulSoup) -> str:
    for selector, attribute in (
        ("meta[property='og:site_name']", "content"),
        ("meta[name='application-name']", "content"),
    ):
        element = soup.select_one(selector)
        if element and element.get(attribute):
            return str(element[attribute]).strip()[:500]
    for script in soup.select("script[type='application/ld+json']"):
        try:
            value = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") in {
                "Organization",
                "Corporation",
                "LocalBusiness",
            }:
                if item.get("name"):
                    return str(item["name"]).strip()[:500]
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return re.split(r"\s*[|｜–—]\s*", title, maxsplit=1)[0].strip()[:500]


def _extract_email(soup: BeautifulSoup, text: str) -> str:
    candidates = []
    for anchor in soup.select("a[href^='mailto:']"):
        value = anchor.get("href", "").split(":", 1)[-1].split("?", 1)[0].strip()
        if value:
            candidates.append(value)
    candidates.extend(re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text))
    unique = list(dict.fromkeys(value.lower() for value in candidates if len(value) <= 320))
    priorities = ("info@", "contact@", "inquiry@", "sales@", "support@")
    return next(
        (value for prefix in priorities for value in unique if value.startswith(prefix)),
        unique[0] if unique else "",
    )


def _extract_phone(text: str) -> str:
    patterns = (
        r"(?:TEL|電話|Phone)\s*[：:]?\s*(0\d{1,4}[\s\-‐‑‒–—ー]\d{1,4}[\s\-‐‑‒–—ー]\d{3,4})",
        r"(?<!\d)(0\d{1,4}[\-‐‑‒–—ー]\d{1,4}[\-‐‑‒–—ー]\d{3,4})(?!\d)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return re.sub(r"[\s‐‑‒–—ー]", "-", match.group(1))[:100]
    return ""


def _extract_location(text: str) -> tuple[str, str, str]:
    prefecture = next((value for value in PREFECTURES if value in text), "")
    if not prefecture:
        return "", "", ""
    start = text.find(prefecture)
    fragment = text[start : start + 160]
    city_match = re.match(re.escape(prefecture) + r"([^\s、,]{1,30}?(?:市|区|町|村))", fragment)
    city = city_match.group(1) if city_match else ""
    address_match = re.match(r"[^\n。]{2,120}", fragment)
    return (address_match.group(0).strip() if address_match else prefecture), prefecture, city


def _social_links(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    result = {
        key: ""
        for key in (
            "instagram_url",
            "x_url",
            "tiktok_url",
            "facebook_url",
            "youtube_url",
            "line_url",
        )
    }
    for anchor in soup.select("a[href]"):
        url = _clean_url(str(anchor.get("href", "")), base_url)
        if not url:
            continue
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        path = urlsplit(url).path.lower()
        if host == "instagram.com" and not any(
            part in path for part in ("/p/", "/reel/", "/share")
        ):
            result["instagram_url"] = result["instagram_url"] or url
        elif host in {"x.com", "twitter.com"} and not any(
            part in path for part in ("/intent/", "/share")
        ):
            result["x_url"] = result["x_url"] or url
        elif host == "tiktok.com" and "/share" not in path:
            result["tiktok_url"] = result["tiktok_url"] or url
        elif host == "facebook.com" and not any(
            part in path for part in ("/sharer", "/dialog", "/login")
        ):
            result["facebook_url"] = result["facebook_url"] or url
        elif host in {"youtube.com", "youtu.be"}:
            result["youtube_url"] = result["youtube_url"] or url
        elif host in {"line.me", "lin.ee"}:
            result["line_url"] = result["line_url"] or url
    return result


def _contact_url(soup: BeautifulSoup, base_url: str) -> str:
    base_host = (urlsplit(base_url).hostname or "").lower()
    scored = []
    for anchor in soup.select("a[href]"):
        label = anchor.get_text(" ", strip=True).lower()
        href = str(anchor.get("href", ""))
        combined = f"{label} {href.lower()}"
        if not any(hint in combined for hint in CONTACT_HINTS):
            continue
        url = _clean_url(href, base_url)
        if url and (urlsplit(url).hostname or "").lower() == base_host:
            score = 2 if "お問い合わせ" in label or "contact" in label else 1
            scored.append((score, url))
    return max(scored, default=(0, ""))[1]


def discover_important_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = (urlsplit(base_url).hostname or "").lower().removeprefix("www.")
    base_path = urlsplit(base_url).path.rstrip("/") or "/"
    scored: dict[str, int] = {}
    for anchor in soup.select("a[href]"):
        url = _clean_url(str(anchor.get("href", "")), base_url)
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if not url or host != base_host:
            continue
        path = parsed.path.rstrip("/") or "/"
        if path == base_path or re.search(r"\.(?:pdf|jpe?g|png|gif|zip)$", path, re.IGNORECASE):
            continue
        label = anchor.get_text(" ", strip=True).lower()
        combined = f"{label} {path.lower()}"
        score = max(
            (
                priority
                for priority, hints in IMPORTANT_PAGE_HINTS
                if any(hint in combined for hint in hints)
            ),
            default=0,
        )
        if score:
            normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            scored[normalized] = max(score, scored.get(normalized, 0))
    return [
        url
        for url, _ in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[
            :MAX_SECONDARY_PAGES
        ]
    ]


def merge_page_data(target: PageData, source: PageData, source_url: str) -> None:
    for field in (
        "company_name",
        "phone",
        "email",
        "address",
        "prefecture",
        "city",
        "contact_url",
        "instagram_url",
        "x_url",
        "tiktok_url",
        "facebook_url",
        "youtube_url",
        "line_url",
        "business_summary",
    ):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
    if source.website_text and source.website_text not in target.website_text:
        target.website_text = (f"{target.website_text}\n\n[{source_url}]\n{source.website_text}")[
            :100_000
        ]


def extract_page(html: str, base_url: str) -> PageData:
    soup = BeautifulSoup(html, "html.parser")
    summary_tag = soup.select_one("meta[name='description'], meta[property='og:description']")
    summary = str(summary_tag.get("content", "")).strip() if summary_tag else ""
    company_name = _extract_company_name(soup)
    for element in soup.select("script, style, noscript, svg, template"):
        element.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    address, prefecture, city = _extract_location(text)
    data = PageData(
        company_name=company_name,
        phone=_extract_phone(text),
        email=_extract_email(soup, text),
        address=address,
        prefecture=prefecture,
        city=city,
        contact_url=_contact_url(soup, base_url),
        business_summary=(summary or text[:500])[:2000],
        website_text=text[:100_000],
    )
    for key, value in _social_links(soup, base_url).items():
        setattr(data, key, value)
    return data


def scrape_company(url: str) -> tuple[FetchedPage, PageData]:
    fetcher = SafeFetcher()
    try:
        page = fetcher.fetch_html(url)
        data = extract_page(page.html, page.url)
        data.scraped_urls = [page.url]
        primary_host = (urlsplit(page.url).hostname or "").lower().removeprefix("www.")
        for secondary_url in discover_important_urls(page.html, page.url):
            try:
                secondary_page = fetcher.fetch_html(secondary_url)
            except ScrapeError:
                continue
            secondary_host = (
                (urlsplit(secondary_page.url).hostname or "").lower().removeprefix("www.")
            )
            if secondary_host != primary_host:
                continue
            merge_page_data(
                data,
                extract_page(secondary_page.html, secondary_page.url),
                secondary_page.url,
            )
            if secondary_page.url not in data.scraped_urls:
                data.scraped_urls.append(secondary_page.url)
        return page, data
    finally:
        fetcher.close()
