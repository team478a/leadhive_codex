"""Conservative page-level checks after GET; never learns a whole domain."""

from urllib.parse import urlsplit

from bs4 import BeautifulSoup


def page_reason(html: str, url: str) -> str:
    from app.services.collection_discovery import classify_hit

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    kind, reason = classify_hit({"link": url, "title": title})
    if kind in {"SOCIAL", "PORTAL_DIRECTORY", "OTHER"} or (
        kind == "JOB_PR" and reason == "EXTERNAL_PLATFORM"
    ):
        return "NON_COMPANY_SOURCE"
    # Some business contact templates use <article>/og:type=article too.
    # A contact-path form is not a comparison article merely because of its wrapper.
    from app.services.contact_discovery import is_contact_form

    path = urlsplit(url).path.lower()
    if any(hint in path for hint in ("contact", "inquiry", "otoiawase", "toiawase")) and any(
        is_contact_form(form) for form in soup.select("form")
    ):
        return ""
    if kind == "JOB_PR":
        return (
            "JOB_LISTING"
            if soup.select_one("[itemtype*='JobPosting']")
            or any(
                text in soup.get_text(" ", strip=True)
                for text in ("求人検索", "求人を検索", "求人件数")
            )
            else ""
        )
    og_type = soup.select_one("meta[property='og:type']")
    is_article = bool(
        (og_type and str(og_type.get("content", "")).lower() == "article")
        or soup.select_one("article, [itemtype*='Article']")
    )
    if kind == "ARTICLE" and (is_article or reason == "AGGREGATION_TITLE"):
        return "ARTICLE_PAGE"
    return ""
