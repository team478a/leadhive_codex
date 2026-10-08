"""Bounded literal excerpts for Human review, never an industry classifier."""

import re
import unicodedata
from datetime import timedelta

from app.services.industry_aliases import terms_for
from app.services.industry_role_hints import context_hint, hint_order
from app.services.official_site_condition import evaluate_site
from app.services.site_identity_review import official_evidence_url


def hints(db, company, value, now):
    empty = dict(status="UNAVAILABLE", reason="INDUSTRY_SOURCE_UNAVAILABLE", excerpts=[])
    if (
        company.analysis_status != "completed"
        or company.scraped_at is None
        or not now - timedelta(hours=24) <= company.scraped_at <= now
        or evaluate_site(db, company, now)["outcome"] != "MATCH"
    ):
        return empty
    term = unicodedata.normalize("NFKC", value).strip()
    if len(term) < 2 or len(term) > 100:
        return {**empty, "reason": "INDUSTRY_TERM_UNSUPPORTED"}
    terms = terms_for(db, company, term)
    pattern = "|".join(re.escape(item) for item in sorted(terms, key=len, reverse=True))
    stored_urls = company.scraped_urls if isinstance(company.scraped_urls, list) else []
    urls = {url for url in stored_urls if isinstance(url, str)}
    source = stored_urls[0] if stored_urls and isinstance(stored_urls[0], str) else ""
    # Secondary pages have an explicit marker inserted by the existing scraper.
    parts = re.split(r"(?m)^\[(https?://[^\]\r\n]+)\]\s*\n", (company.website_text or "")[:100_000])
    segments = [(source, parts[0])]
    segments.extend(zip(parts[1::2], parts[2::2]))
    excerpts, seen = [], set()
    for source, text in segments:
        if source not in urls:
            continue
        try:
            safe_source = official_evidence_url(company, source)
        except (ValueError, UnicodeError):
            continue
        text = " ".join(unicodedata.normalize("NFKC", text).split())
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 130)
            excerpt = text[start:end]
            key = (safe_source, excerpt)
            if key in seen:
                continue
            seen.add(key)
            excerpts.append(
                dict(
                    text=excerpt,
                    source_url=safe_source,
                    observed_at=company.scraped_at,
                    matched_term=match[0],
                    role_hint=context_hint(excerpt, safe_source, match[0]),
                )
            )
            if len(excerpts) == 60:
                break
        if len(excerpts) == 60:
            break
    excerpts = sorted(excerpts, key=hint_order)[:3]
    return dict(
        status="AVAILABLE" if excerpts else "NO_LITERAL_MATCH",
        reason="INDUSTRY_TEXT_CANDIDATES" if excerpts else "INDUSTRY_TEXT_NOT_FOUND",
        excerpts=excerpts,
        terms=terms,
    )
