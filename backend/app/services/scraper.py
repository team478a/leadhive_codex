import ipaddress
import logging
import re
import socket
import time
import urllib.robotparser
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from html import unescape
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services import site_extraction
from app.services.collection import canonicalize_url
from app.services.contact_discovery import navigation_links, same_site

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
    "hotpepper.jp",
    "beauty.rakuten.co.jp",
    "minimodel.jp",
    "ekiten.jp",
    "hairlog.jp",
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
    field_evidence: dict = dataclass_field(default_factory=dict)
    crawl_errors: list[dict] = dataclass_field(default_factory=list)


def is_aggregator_domain(domain: str) -> bool:
    normalized = domain.lower().rstrip(".").removeprefix("www.")
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
        self.site_root = ""
        self._request_count = 0
        self._started = time.monotonic()
        self._last_request: dict[str, float] = {}

    def close(self):
        self.client.close()

    def _request(
        self, url: str, max_bytes: int, redirects: int = 0, robots_request: bool = False
    ) -> FetchedPage:
        if redirects > 5:
            raise ScrapeError("リダイレクト回数が上限を超えました。")
        normalized, _ = _validated_target(url)
        if self.site_root and not same_site(self.site_root, normalized):
            raise ScrapeError("追加探索の別サイト・HTTP降格への転送は取得しません。")
        if redirects and not robots_request and not self.robots_allowed(normalized):
            raise ScrapeError("転送先のrobots.txtにより解析が許可されていません。")
        if self._request_count >= 32 or time.monotonic() - self._started >= 60:
            raise ScrapeError("Webサイト取得の回数・時間上限に達しました。")
        host = urlsplit(normalized).hostname or ""
        wait = 1 - (time.monotonic() - self._last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        if time.monotonic() - self._started >= 60:
            raise ScrapeError("Webサイト取得の時間上限に達しました。")
        self._request_count += 1
        self._last_request[host] = time.monotonic()
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
                    if time.monotonic() - self._started >= 60:
                        raise ScrapeError("Webサイト取得の時間上限に達しました。")
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
        # Failure to fetch robots is not evidence of a robots prohibition.
        # Propagate the acquisition failure, remaining fail-closed.
        page = self._request(robots_url, 256_000, robots_request=True)
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
    org = site_extraction.organization(soup)
    if org.get("name"):
        return str(org["name"]).strip()[:500]
    for selector in ("meta[property='og:site_name']", "meta[name='application-name']"):
        element = soup.select_one(selector)
        if element and element.get("content"):
            return str(element["content"]).strip()[:500]
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return re.split(r"\s*[|｜–—]\s*", title, maxsplit=1)[0].strip()[:500]


def _extract_email(soup: BeautifulSoup, text: str) -> str:
    return site_extraction.email(soup, text)


def _extract_phone(text: str) -> str:
    return site_extraction.phone(text)


def _extract_location(text: str) -> tuple[str, str, str]:
    prefecture = next((value for value in PREFECTURES if value in text), "")
    if not prefecture:
        return "", "", ""
    start = text.find(prefecture)
    fragment = text[start : start + 160]
    fragment = re.split(
        r"\s+(?:TEL|FAX|Phone|電話|メール|営業時間|お問い合わせ|対応地域)",
        fragment,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
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
    # Use the crawler's ranking rather than breaking equal scores by URL text.
    # Keep this field an observed anchor destination, not iframe/form proof.
    anchors = "".join(str(anchor) for anchor in soup.select("a[href]"))
    links = navigation_links(anchors, base_url, base_url)
    return links[0] if links else ""


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
            if field in source.field_evidence:
                target.field_evidence[field] = source.field_evidence[field]
    if source.website_text and source.website_text not in target.website_text:
        target.website_text = (f"{target.website_text}\n\n[{source_url}]\n{source.website_text}")[
            :100_000
        ]


def extract_page(html: str, base_url: str) -> PageData:
    soup = BeautifulSoup(html, "html.parser")
    summary_tag = soup.select_one("meta[name='description'], meta[property='og:description']")
    summary = str(summary_tag.get("content", "")).strip() if summary_tag else ""
    company_name = _extract_company_name(soup)
    org = site_extraction.organization(soup)
    for element in soup.select("script, style, noscript, svg, template"):
        element.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    location, address_method = site_extraction.location_text(soup, text, org)
    address, prefecture, city = _extract_location(location)
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
    for field_name, method in (
        ("company_name", "JSON_LD_NAME" if org.get("name") else "METADATA_OR_TITLE_CANDIDATE"),
        ("address", address_method),
        ("phone", "PHONE_TEXT"),
        ("email", "MAILTO_OR_TEXT"),
        ("contact_url", "CONTACT_LINK"),
    ):
        value = getattr(data, field_name)
        if value:
            data.field_evidence[field_name] = {
                "value": value,
                "source_url": base_url,
                "method": method,
                "verified": False,
            }
    for key, value in _social_links(soup, base_url).items():
        setattr(data, key, value)
    return data


def scrape_company(url: str) -> tuple[FetchedPage, PageData]:
    fetcher = SafeFetcher()
    try:
        page = fetcher.fetch_html(url)
        fetcher.site_root = page.url
        data = extract_page(page.html, page.url)
        data.scraped_urls = [page.url]
        primary_host = (urlsplit(page.url).hostname or "").lower().removeprefix("www.")
        queue = discover_important_urls(page.html, page.url)
        visited = {page.url.rstrip("/")}
        count = 0
        while queue and count < MAX_SECONDARY_PAGES:
            secondary_url = queue.pop(0)
            if secondary_url.rstrip("/") in visited:
                continue
            visited.add(secondary_url.rstrip("/"))
            count += 1
            try:
                secondary_page = fetcher.fetch_html(secondary_url)
            except ScrapeError as exc:
                data.crawl_errors.append(
                    {"requested_url": secondary_url, "reason": exc.public_message}
                )
                continue
            secondary_host = (
                (urlsplit(secondary_page.url).hostname or "").lower().removeprefix("www.")
            )
            if secondary_host != primary_host or not same_site(page.url, secondary_page.url):
                data.crawl_errors.append(
                    {"requested_url": secondary_url, "reason": "CROSS_SITE_REDIRECT"}
                )
                continue
            queue.extend(
                navigation_links(
                    secondary_page.html, secondary_page.url, page.url, contact_context=True
                )
            )
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
