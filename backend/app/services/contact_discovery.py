"""Bounded, GET-only contact navigation; discovered links are not send permission."""

import ipaddress
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


def external_contact_links(html: str, base: str, root: str) -> list[dict[str, str]]:
    """Unverified provenance only; these URLs are never added to the crawl queue."""
    candidates: dict[str, dict[str, str]] = {}
    for anchor in BeautifulSoup(html, "html.parser").select("a[href]"):
        label = re.sub(r"\s+", "", anchor.get_text(" ", strip=True)).lower()
        if label not in {re.sub(r"\s+", "", hint) for hint in HINTS}:
            continue
        try:
            parsed = urlsplit(urljoin(base, str(anchor.get("href") or "")))
            host = (parsed.hostname or "").lower().rstrip(".")
            if (
                parsed.scheme != "https"
                or not host
                or parsed.username
                or parsed.password
                or parsed.port not in {None, 443}
                or "." not in host
                or host.endswith((".localhost", ".local", ".internal", ".test"))
                or same_site(root, parsed.geturl())
            ):
                continue
            try:
                if not ipaddress.ip_address(host).is_global:
                    continue
            except ValueError:
                pass
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
            if parsed.path.lower().endswith((".pdf", ".jpg", ".png", ".zip")):
                continue
        except ValueError:
            continue
        candidates.setdefault(url, {"url": url, "source_url": base, "label": label[:100]})
        if len(candidates) >= 8:
            break
    return list(candidates.values())


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


def custom_contact_containers(html: str) -> list[Tag]:
    """Observe narrowly identified JS contact controls, never an HTTP form contract."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[Tag] = []
    for container in soup.select("div, section, fieldset, [role='form']"):
        identity = " ".join(
            str(container.get(key) or "") for key in ("id", "aria-label", "role")
        ).lower()
        if container.get("role") != "form" and not any(hint in identity for hint in HINTS):
            continue
        if (
            container.name == "form"
            or container.find_parent("form")
            or container.select_one("form")
        ):
            continue
        if any(
            parent.has_attr("hidden")
            or str(parent.get("aria-hidden") or "").lower() == "true"
            or re.search(
                r"display\s*:\s*none|visibility\s*:\s*hidden", str(parent.get("style") or ""), re.I
            )
            for parent in [container, *container.parents]
            if isinstance(parent, Tag)
        ):
            continue
        controls = container.select("input, textarea, select")
        if not controls or any(control.has_attr("form") for control in controls):
            continue
        if container.select_one("input[type='password'], input[type='search']"):
            continue
        if not container.select_one("input[type='email']:not([disabled])"):
            continue
        if not container.select_one("textarea:not([disabled])"):
            continue
        buttons = container.select("button, input[type='submit'], input[type='button']")
        if not any(
            not button.has_attr("disabled")
            and re.search(
                r"送信|確認|send|submit|confirm",
                button.get_text(" ", strip=True) + str(button.get("value") or ""),
                re.I,
            )
            for button in buttons
        ):
            continue
        names = [str(control.get("name") or "") for control in controls]
        if not all(names) or len(names) != len(set(names)) or len(controls) > 100:
            continue
        candidates.append(container)
        if len(candidates) > 32:
            return []
    # Keep the smallest explicitly identified container, not each ancestor.
    return [
        candidate
        for candidate in candidates
        if not any(
            other is not candidate and any(parent is candidate for parent in other.parents)
            for other in candidates
        )
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


def is_contact_path(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return bool(
        re.search(
            r"(?:^|[/_-])(?:contact|inquiry|inquire|otoiawase|toiawase|form)(?:$|[/_.-])",
            path,
        )
    )


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
            re.search(r"^/(?:blog|news|post|lab|column|article|srv)(?:/|$)", parsed.path.lower())
            and not label_contact_cta
        ):
            continue
        path_hint = bool(
            re.search(
                r"(?:^|[/_-])(?:contact|inquiry|inquire|otoiawase|toiawase)(?:$|[/_.-])",
                parsed.path.lower(),
            )
        )
        # A direct contact label outranks testimonials/service copy mentioning
        # inquiries. Otherwise a large site's incidental links exhaust the
        # bounded crawl before its general contact destination is reached.
        direct_label = re.sub(r"\s+", "", label) in {re.sub(r"\s+", "", hint) for hint in HINTS}
        score = (
            120
            if direct_label
            else 100
            if label_contact
            else 90
            if path_hint
            else 0
        )
        # Dedicated contact paths beat incidental article text, including a
        # footer link whose wording is longer than the exact contact label.
        if path_hint:
            score += 10
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
    resolved_urls: dict[str, str] | None = None,
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
    if (
        root_soup.select_one("form")
        or has_contact_anchor
        or embedded_form_providers(root_html)
        or custom_contact_containers(root_html)
    ):
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
            base = (resolved_urls or {}).get(url, url)
            visited.add(base.rstrip("/"))
            children = navigation_links(html, base, root, contact_context=explicit)
            queue[0:0] = [
                (child, True, depth + 1) for child in children if child.rstrip("/") not in visited
            ]
