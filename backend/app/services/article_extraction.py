"""Rule-based extraction of company candidates from saved article HTML."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

EXTRACTOR_VERSION = "article-rule-1"
MAX_CONTEXT_LENGTH = 300
MAX_ENTRY_COUNT = 100

_HEADING_PREFIX = re.compile(
    r"^\s*(?:(?:第\s*)?[0-9０-９一二三四五六七八九十]+\s*(?:位|位目)?[.．、:：)）]\s*|"
    r"第\s*[0-9０-９一二三四五六七八九十]+\s*位\s*|"
    r"[0-9０-９一二三四五六七八九十]+\s*位\s*)"
)
_PAREN_SUFFIX = re.compile(r"\s*[（(\[].*?[）)\]]\s*$")
_LEGAL_FORMS = (
    "株式会社",
    "有限会社",
    "合同会社",
    "合名会社",
    "合資会社",
    "一般社団法人",
    "公益社団法人",
    "一般財団法人",
    "公益財団法人",
    "NPO法人",
    "医療法人",
    "学校法人",
    "社会福祉法人",
    "税理士法人",
    "弁護士法人",
    "(株)",
    "（株）",
    "(有)",
    "（有）",
)
_BAD_NAME = re.compile(
    r"まとめ|よくある質問|選び方|費用相場|比較表|おすすめポイント|メリット|注意点|"
    r"(?:とは|しよう|[?？])$"
)
_LINK_LABEL = re.compile(
    r"公式サイト|公式|ホームページ|HP|Webサイト|ウェブサイト|詳細はこちら", re.I
)
_PUBLISHER_SUFFIXES = {
    "co.uk",
    "org.uk",
    "ac.uk",
    "gov.uk",
    "com.au",
    "net.au",
    "org.au",
    "co.nz",
    "com.br",
    "com.cn",
    "com.sg",
    "com.hk",
    "co.kr",
    "co.in",
    "co.jp",
    "ne.jp",
    "or.jp",
    "ac.jp",
    "go.jp",
    "ed.jp",
    "gr.jp",
    "lg.jp",
}
_TRACKER_HOSTS = (
    "a8.net",
    "valuecommerce.ne.jp",
    "valuecommerce.com",
    "felmat.net",
    "afb.jp",
    "もしもアフィリエイト.jp",
    "moshimo.com",
    "accesstrade.ne.jp",
)
_PLATFORM_HOSTS = (
    "instagram.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "linkedin.com",
    "wantedly.com",
    "indeed.com",
    "求人ボックス.com",
    "hotpepper.jp",
    "tabelog.com",
    "gnavi.co.jp",
    "epark.jp",
    "minimodel.jp",
    "ekiten.jp",
    "hairlog.jp",
    "wikipedia.org",
    "itp.ne.jp",
    "townpage.goo.ne.jp",
    "mapion.co.jp",
    "web-kanji.com",
    "probel.jp",
    "dreamnews.jp",
    "lemon8-app.com",
    "livejapan.com",
    "gurumeguide.cpay.jp",
    "travelbook.co.jp",
    "retty.me",
    "jalan.net",
    "tabiiro.jp",
    "precious.jp",
    "kit-press.com",
    "townwork.net",
    "baitoru.com",
    "next.rikunabi.com",
    "r-agent.com",
)
_STRUCTURE_CLASS = re.compile(
    r"sidebar|related|ranking-widget|breadcrumb|comment|author|share", re.I
)
_NON_NAME_HEADINGS = re.compile(
    r"まとめ|よくある質問|選び方|費用相場|比較表|おすすめポイント|メリット|注意点"
)


@dataclass(frozen=True)
class ArticleEntry:
    order: int
    name: str
    name_key: str
    link_url: str
    link_kind: str
    pattern: str
    locator: str
    context: str
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionResult:
    entries: tuple[ArticleEntry, ...]
    page_kind: str
    publisher_host: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _Block:
    name: str
    container: Tag
    locator: str
    context: str
    pattern: str
    alt_only: bool = False


def _host(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("article_url must be an absolute HTTP(S) URL")
    return parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()


def _registered_domain(host: str) -> str:
    labels = host.split(".")
    if len(labels) < 2:
        return host
    suffix = ".".join(labels[-2:])
    if suffix in _PUBLISHER_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return suffix


def _element_marker(element: Tag) -> str:
    marker_values = [str(element.get("id", ""))]
    classes = element.get("class")
    if isinstance(classes, str):
        marker_values.append(classes)
    elif isinstance(classes, list):
        marker_values.extend(str(value) for value in classes)
    return " ".join(marker_values)


def _is_sponsored(container: Tag) -> bool:
    for element in container.find_all(True):
        if re.search(r"sponsor|advert|ad-label", _element_marker(element), re.I):
            return True
        label = _text(element).strip()
        if re.fullmatch(r"(?:PR|AD|広告|スポンサー)", label, re.I):
            return True
    return False


def _text(element: Tag) -> str:
    return " ".join(element.stripped_strings)


def _main_content(soup: BeautifulSoup) -> Tag:
    for selector in ("main", "article", '[role="main"]'):
        found = soup.select_one(selector)
        if isinstance(found, Tag):
            root = found
            break
    else:
        root = soup.body or soup
    for element in list(root.select("header, nav, footer, aside")):
        element.decompose()
    for element in list(root.find_all(True)):
        if _STRUCTURE_CLASS.search(_element_marker(element)):
            element.decompose()
    return root


def _name_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name)
    normalized = re.sub(r"\s+", "", normalized)
    for legal_form in _LEGAL_FORMS:
        normalized = normalized.replace(unicodedata.normalize("NFKC", legal_form), "")
    return normalized


def _clean_heading(value: str) -> str:
    cleaned = _HEADING_PREFIX.sub("", value).strip()
    cleaned = _PAREN_SUFFIX.sub("", cleaned).strip(" \t　:：-‐–—")
    return cleaned


def _is_name(value: str) -> bool:
    return 2 <= len(value) <= 60 and not _BAD_NAME.search(value)


def _candidate_name(container: Tag, raw_name: str, pattern: str) -> str:
    if pattern == "HEADING":
        return _clean_heading(raw_name)
    emphasized = container.find(["strong", "b"])
    if isinstance(emphasized, Tag) and _text(emphasized):
        return _clean_heading(_text(emphasized))
    return _clean_heading(raw_name)


def _heading_blocks(root: Tag) -> list[_Block]:
    blocks: list[_Block] = []
    headings = root.find_all(["h2", "h3"])
    for index, heading in enumerate(headings, start=1):
        name = _clean_heading(_text(heading))
        alt_only = False
        if not name:
            image = heading.find("img", alt=True)
            if isinstance(image, Tag):
                name = _clean_heading(str(image.get("alt", "")))
                alt_only = bool(name)
        if not name:
            continue
        chunks = [heading]
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2", "h3"}:
                break
            if isinstance(sibling, Tag):
                chunks.append(sibling)
        wrapper = BeautifulSoup("<div></div>", "html.parser").div
        if wrapper is None:
            continue
        for chunk in chunks:
            wrapper.append(BeautifulSoup(str(chunk), "html.parser"))
        context = " ".join(_text(chunk) for chunk in chunks)
        blocks.append(
            _Block(name, wrapper, f"h{heading.name[1]}[{index}]", context, "HEADING", alt_only)
        )
    return blocks


def _table_blocks(root: Tag) -> list[_Block]:
    blocks: list[_Block] = []
    for table_index, table in enumerate(root.find_all("table"), start=1):
        rows = table.find_all("tr")
        header = next((row for row in rows if row.find("th")), None)
        if header is None:
            continue
        header_cells = header.find_all(["th", "td"], recursive=False)
        name_column = next(
            (
                index
                for index, cell in enumerate(header_cells)
                if re.search(r"会社名|企業名|サービス名|社名", _text(cell))
            ),
            None,
        )
        if name_column is None:
            continue
        data_index = 0
        for row in rows[rows.index(header) + 1 :]:
            cells = row.find_all(["th", "td"], recursive=False)
            if name_column >= len(cells):
                continue
            cell = cells[name_column]
            name = _text(cell)
            if not name:
                continue
            data_index += 1
            blocks.append(
                _Block(name, row, f"table[{table_index}]/tr[{data_index}]", _text(row), "TABLE")
            )
    return blocks


def _list_blocks(root: Tag) -> list[_Block]:
    blocks: list[_Block] = []
    for list_index, listing in enumerate(root.find_all(["ol", "ul"]), start=1):
        for item_index, item in enumerate(listing.find_all("li", recursive=False), start=1):
            text = _text(item)
            if text:
                blocks.append(
                    _Block(
                        text, item, f"{listing.name}[{list_index}]/li[{item_index}]", text, "LIST"
                    )
                )
    return blocks


def _card_blocks(root: Tag) -> list[_Block]:
    groups: dict[tuple[int, tuple[str, ...]], list[Tag]] = {}
    for element in root.find_all(True):
        class_values = element.get("class")
        if isinstance(class_values, str):
            class_list = [class_values]
        elif isinstance(class_values, list):
            class_list = [str(value) for value in class_values]
        else:
            class_list = []
        classes = tuple(sorted(class_list))
        if not classes:
            continue
        parent_id = id(element.parent)
        groups.setdefault((parent_id, classes), []).append(element)
    blocks: list[_Block] = []
    for siblings in groups.values():
        if len(siblings) < 3:
            continue
        for index, card in enumerate(siblings, start=1):
            title = card.find(["h2", "h3", "h4", "strong", "b"])
            name = _text(title) if isinstance(title, Tag) else _text(card)
            if name:
                blocks.append(_Block(name, card, f"card[{index}]", _text(card), "CARD"))
        if blocks:
            return blocks
    return blocks


def _absolute_url(href: str, article_url: str) -> str:
    absolute = urljoin(article_url, href.strip())
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    netloc = host
    if parsed.port and not (
        (parsed.scheme.lower() == "http" and parsed.port == 80)
        or (parsed.scheme.lower() == "https" and parsed.port == 443)
    ):
        netloc = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _link_type(url: str, publisher_host: str) -> tuple[str, str]:
    if not url:
        return "NONE", ""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if (
        re.search(r"/(?:go|out|redirect)(?:/|$)", parsed.path.lower())
        or query_keys.intersection({"url", "u"})
        or any(_host_matches(host, domain) for domain in _TRACKER_HOSTS)
    ):
        return "REDIRECT_TRACKER", "TRACKED_LINK_NOT_FOLLOWED"
    if any(_host_matches(host, domain) for domain in _PLATFORM_HOSTS):
        return "PLATFORM", "PLATFORM_LINK"
    if _registered_domain(host) == _registered_domain(publisher_host):
        return "SAME_SITE", "INTERNAL_DETAIL_LINK"
    return "EXTERNAL_SITE", ""


def _links(container: Tag, article_url: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for anchor in container.find_all("a", href=True):
        url = _absolute_url(str(anchor.get("href", "")), article_url)
        if url:
            found.append((_text(anchor), url))
    return found


def _extract_from_block(block: _Block, article_url: str, publisher_host: str) -> ArticleEntry:
    name = _candidate_name(block.container, block.name, block.pattern)
    reasons: list[str] = []
    if not _is_name(name):
        reasons.append("INVALID_OR_STRUCTURAL_NAME")
    if block.alt_only:
        reasons.append("IMAGE_ALT_ONLY")
    if not any(form in name for form in _LEGAL_FORMS):
        reasons.append("NO_LEGAL_FORM")
    links = _links(block.container, article_url)
    labeled = [item for item in links if _LINK_LABEL.search(item[0])]
    selected = labeled if labeled else links
    unique_urls = list(dict.fromkeys(url for _, url in selected))
    if len(unique_urls) > 1 and not labeled:
        link_url = ""
        link_kind, link_reason = "NONE", "AMBIGUOUS_LINK"
    else:
        link_url = unique_urls[0] if unique_urls else ""
        link_kind, link_reason = _link_type(link_url, publisher_host)
    if link_reason:
        reasons.append(link_reason)
    if _is_sponsored(block.container):
        reasons.append("SPONSORED_BLOCK")
    link_host = (urlsplit(link_url).hostname or "").lower() if link_url else ""
    same_publisher_domain = bool(link_host) and _registered_domain(link_host) == _registered_domain(
        publisher_host
    )
    if (
        same_publisher_domain
        and link_kind != "REDIRECT_TRACKER"
        and (link_host != publisher_host or bool(labeled))
    ):
        reasons.append("PUBLISHER_SELF")
    duplicate_key = _name_key(name)
    if "PUBLISHER_SELF" in reasons:
        status = "REJECTED"
    elif link_kind == "EXTERNAL_SITE" and not any(
        reason in reasons
        for reason in ("INVALID_OR_STRUCTURAL_NAME", "IMAGE_ALT_ONLY", "SPONSORED_BLOCK")
    ):
        status = "LINKED"
    elif link_kind in {"SAME_SITE", "REDIRECT_TRACKER", "PLATFORM", "NONE"}:
        status = "NAME_ONLY" if _is_name(name) else "REJECTED"
    else:
        status = "REJECTED"
    if not _is_name(name) or block.alt_only or "SPONSORED_BLOCK" in reasons:
        status = "REJECTED"
    return ArticleEntry(
        order=0,
        name=name,
        name_key=duplicate_key,
        link_url=link_url,
        link_kind=link_kind,
        pattern=block.pattern,
        locator=block.locator,
        context=block.context[:MAX_CONTEXT_LENGTH],
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def extract_entries(
    html: str, article_url: str, *, max_entries: int = MAX_ENTRY_COUNT
) -> ExtractionResult:
    """Extract repeatable company-list blocks without network or persistence access."""
    publisher_host = _host(article_url)
    if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
        raise ValueError("max_entries must be a positive integer")
    entry_limit = min(max_entries, MAX_ENTRY_COUNT)
    soup = BeautifulSoup(html, "html.parser")
    root = _main_content(soup)
    if not _text(root):
        return ExtractionResult((), "UNSUPPORTED", publisher_host, ("NO_STATIC_CONTENT",))
    patterns = (
        ("HEADING", _heading_blocks),
        ("TABLE", _table_blocks),
        ("LIST", _list_blocks),
        ("CARD", _card_blocks),
    )
    chosen: list[_Block] = []
    chosen_pattern = ""
    for pattern, extractor in patterns:
        candidates = extractor(root)
        if len(candidates) >= 3:
            chosen, chosen_pattern = candidates, pattern
            break
    if not chosen:
        return ExtractionResult((), "NOT_LIST", publisher_host, ())
    warnings: list[str] = []
    for pattern, extractor in patterns:
        if pattern == chosen_pattern:
            continue
        if len(extractor(root)) >= 3:
            warnings.append(f"MIXED_PATTERN:{pattern}")
    if len(chosen) > entry_limit:
        chosen = chosen[:entry_limit]
        warnings.append("ENTRY_LIMIT")
    raw_entries = [_extract_from_block(block, article_url, publisher_host) for block in chosen]
    seen: set[str] = set()
    entries: list[ArticleEntry] = []
    for order, entry in enumerate(raw_entries, start=1):
        reasons = list(entry.reasons)
        status = entry.status
        if entry.name_key in seen:
            status = "REJECTED"
            reasons.append("DUPLICATE_IN_ARTICLE")
        else:
            seen.add(entry.name_key)
        entries.append(
            ArticleEntry(
                order=order,
                name=entry.name,
                name_key=entry.name_key,
                link_url=entry.link_url,
                link_kind=entry.link_kind,
                pattern=entry.pattern,
                locator=entry.locator,
                context=entry.context,
                status=status,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )
    return ExtractionResult(tuple(entries), "LIST_ARTICLE", publisher_host, tuple(warnings))
