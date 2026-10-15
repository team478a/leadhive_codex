"""Bounded, GET-only contact navigation; discovered links are not send permission."""

import re
from collections.abc import Iterator
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

HINTS = (
    "contact",
    "inquiry",
    "inquire",
    "otoiawase",
    "toiawase",
    "お問い合わせ",
    "問合せ",
    "問い合わせ",
    "ご相談",
)
FALLBACK_PATHS = (
    "/contact",
    "/contact-us",
    "/inquiry",
    "/inquiry-form",
    "/contact-form",
    "/form",
    "/otoiawase",
    "/toiawase",
)


def embedded_form_providers(html: str) -> list[str]:
    """Presence evidence only: scripts/iframes do not prove a rendered contact form."""
    soup = BeautifulSoup(html, "html.parser")
    sources = " ".join(str(node) for node in soup.select("script, iframe")).lower()
    patterns = {
        "HUBSPOT": ("hbspt.forms.create", "js.hsforms.net/forms/", "js.hsforms.com/forms/"),
        "FORMRUN": ("sdk.form.run", "form.run/embed", "formrun.jp/embed"),
        "GOOGLE_FORMS": ("docs.google.com/forms/",),
        "TYPEFORM": ("embed.typeform.com", "typeform.com/to/"),
        "TAYORI": ("tayori.com/form/",),
        "MICROSOFT_FORMS": ("forms.office.com/pages/", "forms.office.com/r/"),
    }
    return [
        name for name, markers in patterns.items() if any(marker in sources for marker in markers)
    ]


def is_contact_form(form: Tag, *, contact_context: bool = False) -> bool:
    """Exclude login/search/subscription forms without treating embeds as proof."""
    if form.select_one("input[type='password'], input[type='search']"):
        return False
    if form.select_one("textarea"):
        return True
    for field in form.select("input, select"):
        identity = f"{field.get('name', '')} {field.get('id', '')}".lower()
        if str(field.get("type", "text")).lower() not in {"hidden", "submit", "button"} and any(
            word in identity for word in ("message", "inquiry", "inquire", "comment", "detail")
        ):
            return True
    visible = [
        field
        for field in form.select("input, select")
        if str(field.get("type", "text")).lower()
        not in {"hidden", "submit", "button", "checkbox", "radio"}
    ]
    text = form.get_text(" ", strip=True).lower()
    if len(visible) >= 2 and any(hint in text for hint in HINTS):
        return True
    # Contact pages often use a simple name/email-only form without a message
    # textarea, and the labels may be outside the <form>. The page URL or its
    # navigation link is stronger context than the form's own copy. This only
    # marks a candidate for review; it never authorizes submission.
    identities = " ".join(
        f"{field.get('name', '')} {field.get('id', '')} {field.get('placeholder', '')} "
        f"{field.get('aria-label', '')}"
        for field in visible
    ).lower()
    if contact_context and len(visible) >= 2:
        if any(word in identities for word in ("email", "mail", "name", "company", "phone", "tel")):
            return True
        if any(hint in text for hint in ("名前", "氏名", "メール", "電話", "会社名")):
            return True
    return False


def same_site(left: str, right: str) -> bool:
    a, b = urlsplit(left), urlsplit(right)
    return (
        a.scheme in {"http", "https"}
        and b.scheme in {"http", "https"}
        and (a.hostname or "").removeprefix("www.") == (b.hostname or "").removeprefix("www.")
        and a.port in {None, 80, 443}
        and b.port in {None, 80, 443}
        and not a.username
        and not b.username
        and not (a.scheme == "https" and b.scheme == "http")
    )


def is_contact_path(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return bool(
        re.search(
            r"(?:^|[/_-])(?:contact|inquiry|inquire|otoiawase|toiawase|form)(?:$|[/_.-])",
            path,
        )
    )


def navigation_links(
    html: str, base: str, root: str, *, contact_context: bool = False
) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ranked: list[tuple[int, str]] = []
    for element in soup.select("a[href], iframe[src]"):
        value = str(element.get("href") or element.get("src") or "").strip()
        if not value or value.startswith(("mailto:", "tel:", "javascript:")):
            continue
        label = element.get_text(" ", strip=True).lower()
        fragment = urlsplit(value).fragment.lower()
        fragment_contact = bool(
            fragment
            and any(hint in fragment for hint in ("contact", "inquiry", "otoiawase", "form"))
        )
        label_contact = any(hint in label for hint in HINTS)
        label_contact_cta = label in HINTS or bool(
            re.search(
                r"(?:contact(?: us)?|inquiry|inquire|お問い合わせ|問合せ|問い合わせ|ご相談)"
                r"(?:はこちら|フォーム|する|先|窓口|ページ)?$",
                label,
            )
        )
        if value.startswith("#") and not (fragment_contact or label_contact):
            continue
        parsed = urlsplit(urljoin(base, value))
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
        try:
            allowed = same_site(root, url)
        except ValueError:
            allowed = False
        if not allowed or parsed.path.lower().endswith((".pdf", ".jpg", ".png", ".zip")):
            continue
        if (
            re.search(r"^/(?:blog|news|lab|column|article|srv)(?:/|$)", parsed.path.lower())
            and not label_contact_cta
        ):
            continue
        path_hint = bool(
            re.search(
                r"(?:^|[/_-])(?:contact|inquiry|inquire|otoiawase|toiawase)(?:$|[/_.-])",
                parsed.path.lower(),
            )
        )
        score = 100 if label_contact else (90 if path_hint or fragment_contact else 0)
        if contact_context and (
            element.name == "iframe"
            or any(hint in label for hint in ("フォーム", "入力", "こちら", "進む"))
            or re.search(r"(?:^|[/_-])form(?:$|[/_.-])", parsed.path.lower())
        ):
            score = max(score, 80)
        if score:
            ranked.append((score, url))
    return list(dict.fromkeys(url for _, url in sorted(ranked, key=lambda item: -item[0])))


def contact_pages(
    root: str,
    cache: dict[str, str],
    saved_contact: str = "",
    *,
    max_pages: int = 12,
    max_depth: int = 3,
) -> Iterator[tuple[str, bool]]:
    """Caller fetches each yielded URL and fills cache before resuming iteration.

    Actual navigation is explored before guessed paths. Failed fetches do not
    expand. Root is already fetched and does not consume the secondary budget.
    """
    queue: list[tuple[str, bool, int]] = []
    root_html = cache[root]
    root_soup = BeautifulSoup(root_html, "html.parser")
    has_contact_anchor = any(
        str(anchor.get("href") or "").startswith("#")
        and (
            any(hint in anchor.get_text(" ", strip=True).lower() for hint in HINTS)
            or any(
                hint in str(anchor.get("href") or "").lower()
                for hint in ("contact", "inquiry", "otoiawase", "form")
            )
        )
        for anchor in root_soup.select("a[href]")
    )
    if root_soup.select_one("form") or has_contact_anchor:
        queue.append((root, True, 0))
    if saved_contact:
        try:
            if same_site(root, saved_contact):
                queue.append((saved_contact, True, 1))
        except ValueError:
            pass
    queue.extend((url, True, 1) for url in navigation_links(root_html, root, root))
    parsed = urlsplit(root)
    fallbacks = [
        (urlunsplit((parsed.scheme, parsed.netloc, path, "", "")), False, 1)
        for path in FALLBACK_PATHS
    ]
    visited: set[str] = set()
    count = 0
    while queue or fallbacks:
        if not queue:
            queue, fallbacks = fallbacks, []
        url, explicit, depth = queue.pop(0)
        key = url.rstrip("/")
        if key in visited:
            continue
        if url != root and count >= max_pages:
            break
        visited.add(key)
        if url != root:
            count += 1
        yield url, explicit
        html = cache.get(url)
        if html and depth < max_depth:
            children = navigation_links(html, url, root, contact_context=explicit)
            queue[0:0] = [
                (child, True, depth + 1) for child in children if child.rstrip("/") not in visited
            ]
