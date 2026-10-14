"""Conservative routing hints for search results; never confirm company identity."""

from urllib.parse import urlsplit, urlunsplit

ARTICLE_PATHS = {"blog", "blogs", "column", "columns", "article", "articles", "news", "media"}
DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx")
# Keep aligned with scraper.AGGREGATOR_DOMAINS. Avoid importing scraper here:
# scraper imports collection.canonicalize_url, so this module must stay leaf-level.
REFERENCE_DOMAINS = {
    "hotpepper.jp", "beauty.rakuten.co.jp", "minimodel.jp", "ekiten.jp", "hairlog.jp",
    "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com",
    "linkedin.com", "wikipedia.org", "itp.ne.jp", "townpage.goo.ne.jp", "mapion.co.jp",
}


def is_reference_host(host: str) -> bool:
    normalized = host.lower().rstrip(".").removeprefix("www.")
    return any(
        normalized == domain or normalized.endswith("." + domain)
        for domain in REFERENCE_DOMAINS
    )


def assess_search_url(url: str) -> dict[str, str]:
    """Classify a URL and provide a same-host homepage hint for article pages."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    path_parts = {part for part in parsed.path.lower().split("/") if part}
    reference = is_reference_host(host)
    document = parsed.path.lower().endswith(DOCUMENT_SUFFIXES)
    article = bool(path_parts & ARTICLE_PATHS)
    kind = (
        "REFERENCE_SITE"
        if reference
        else "REFERENCE_DOCUMENT"
        if document
        else "ARTICLE_OWNER_REVIEW"
        if article
        else "BUSINESS_SITE_REVIEW"
    )
    homepage = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    return {
        "kind": kind,
        "homepage_candidate": homepage if not reference and not document else "",
        "reference_url": url,
        "official_site_status": "NOT_CONFIRMED",
        "business_role_status": "NOT_CONFIRMED",
        "purpose_fit_status": "NOT_EVALUATED",
        "contact_status": "NOT_CHECKED",
    }
