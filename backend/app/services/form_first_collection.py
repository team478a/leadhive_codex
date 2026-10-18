"""Form-first lead discovery using bounded Serper searches and SafeFetcher GETs."""

import logging
import re
import threading
import time
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.config import settings
from app.models import CollectionDiscoveryHit, Company, FormProfile, OperationJob
from app.services.collection import Candidate, canonicalize_url
from app.services.collection_discovery import classify_hit, mark_discovery
from app.services.collection_jobs import duplicate_company
from app.services.contact_discovery import (
    custom_contact_containers,
    embedded_form_providers,
    is_contact_form,
    is_contact_path,
    navigation_links,
    same_site,
)
from app.services.non_company_suspected import evidence as non_company_evidence
from app.services.processing_usage import measured_request
from app.services.scraper import SafeFetcher, ScrapeError, _extract_location, site_extraction
from app.services.site_discovery import is_reference_host
from app.services.source_exclusions import excluded

logger = logging.getLogger("leadhive")

QUERY_TYPES = ("intitle_contact", "inurl_contact", "inurl_inquiry", "form_words")
QUERY_TEMPLATES = {
    "intitle_contact": "intitle:お問い合わせ {keyword}",
    "inurl_contact": "inurl:contact {keyword}",
    "inurl_inquiry": "inurl:inquiry {keyword}",
    "form_words": '"お問い合わせフォーム" {keyword}',
}
EXCLUDED_TERMS = ("-求人", "-採用", "-ポータル", "-ランキング", "-まとめ")
CONTACT_TITLE_MARKERS = ("お問い合わせ", "問合せ", "contact", "inquiry", "資料請求")
PUBLIC_SUFFIXES = (".lg.jp", ".go.jp", ".ed.jp", ".ac.jp")
PUBLIC_PREFIXES = ("city.", "pref.", "town.", "vill.")
FORM_SERVICE_DOMAINS = (
    "form.run",
    "formrun.jp",
    "docs.google.com",
    "typeform.com",
    "tayori.com",
    "forms.office.com",
    "hsforms.com",
    "hubspot.com",
)
COMPANY_LABELS = ("会社名", "商号", "社名", "法人名")
SELLER_LABELS = ("販売業者", "販売事業者")
ADDRESS_LABELS = ("所在地", "本社", "住所", "本店所在地")
PHONE_LABELS = ("電話", "電話番号", "tel")
BUSINESS_LABELS = ("事業内容", "事業概要", "業務内容")
ABOUT_LINK_HINTS = ("会社概要", "会社案内", "企業情報", "about", "company")
TRADE_LINK_HINTS = ("特定商取引法", "特商法")

_HOST_LAST_GET: dict[str, float] = {}
_HOST_GET_LOCK = threading.Lock()


def build_form_first_queries(keywords: list[str], query_types: list[str]) -> list[dict[str, str]]:
    if not keywords or not query_types or any(kind not in QUERY_TEMPLATES for kind in query_types):
        raise ValueError("フォーム起点の検索条件が正しくありません。")
    queries = []
    seen = set()
    for keyword in keywords:
        for kind in query_types:
            query = f"{QUERY_TEMPLATES[kind].format(keyword=keyword)} {' '.join(EXCLUDED_TERMS)}"
            if query not in seen:
                queries.append({"query": query, "query_type": kind, "industry_keyword": keyword})
                seen.add(query)
    return queries


def query_result_type(query: str, mapping: dict[str, dict]) -> tuple[str, str]:
    entry = mapping.get(query) or {}
    return str(entry.get("query_type") or "unknown"), str(entry.get("industry_keyword") or "")


def _public_host(host: str) -> bool:
    normalized = host.lower().rstrip(".").removeprefix("www.")
    return normalized.endswith(PUBLIC_SUFFIXES) or normalized.startswith(PUBLIC_PREFIXES)


def _service_host(host: str) -> bool:
    normalized = host.lower().rstrip(".")
    return any(
        normalized == domain or normalized.endswith("." + domain) for domain in FORM_SERVICE_DOMAINS
    )


def classify_search_result(db, project_id, candidate: Candidate) -> str:
    url = candidate.website_url or ""
    try:
        normalized, host = canonicalize_url(url)
    except (ValueError, UnicodeError):
        return "REJECT_NOT_CONTACT"
    if is_reference_host(host):
        return "REJECT_REFERENCE_HOST"
    if excluded(db, project_id, normalized):
        return "REJECT_EXCLUDED_DOMAIN"
    if _public_host(host):
        return "REJECT_PUBLIC_SECTOR"
    if _service_host(host):
        return "REJECT_EXTERNAL_FORM_SERVICE"
    title = candidate.company_name or ""
    is_candidate = is_contact_path(normalized) or any(
        marker.casefold() in title.casefold() for marker in CONTACT_TITLE_MARKERS
    )
    if not is_candidate:
        return "REJECT_NOT_CONTACT"
    kind, reason = classify_hit({"link": normalized, "title": title})
    if (
        kind in {"SOCIAL", "PORTAL_DIRECTORY", "OTHER"}
        or (kind == "JOB_PR" and reason == "EXTERNAL_PLATFORM")
        or (
            kind == "ARTICLE"
            and reason in {"AGGREGATION_TITLE", "COMPARISON_TITLE_REQUIRES_REVIEW"}
        )
    ):
        return "REJECT_REFERENCE_HOST"
    return "CONTACT_PAGE_CANDIDATE"


def _record_hit(
    db,
    candidate: Candidate,
    classification: str,
    reason: str,
    query_type: str,
    details: dict | None = None,
) -> None:
    if not candidate.discovery_hit_id:
        return
    hit = db.get(CollectionDiscoveryHit, candidate.discovery_hit_id)
    if hit is None:
        return
    hit.classification = classification[:30]
    hit.classification_reason = reason[:100]
    fetch_status = reason if reason in {"FORM_FOUND", "FORM_JS_SUSPECTED", "NO_FORM_ON_PAGE"} else None
    hit.snapshot = {
        **hit.snapshot,
        "form_first_query_type": query_type,
        "form_first_candidate": bool(
            hit.snapshot.get("form_first_candidate") or reason == "CONTACT_PAGE_CANDIDATE"
        ),
        **({"form_first_form_status": fetch_status} if fetch_status else {}),
        **(details or {}),
    }


def _label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2:
            label = cells[0].get_text(" ", strip=True).casefold()
            value = cells[1].get_text(" ", strip=True)
            if label and value:
                values.setdefault(label, value)
    for term in soup.select("dt"):
        value = term.find_next_sibling("dd")
        if value:
            label = term.get_text(" ", strip=True).casefold()
            text = value.get_text(" ", strip=True)
            if label and text:
                values.setdefault(label, text)
    return values


def _lookup_label(values: dict[str, str], labels: tuple[str, ...]) -> str:
    for label, value in values.items():
        normalized = re.sub(r"[\s：:]", "", label)
        if any(re.sub(r"[\s：:]", "", item).casefold() == normalized for item in labels):
            return value[:5000]
    return ""


def _page_facts(html: str, url: str) -> dict[str, dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    pairs = _label_value_pairs(soup)
    org = site_extraction.organization(soup)
    text = soup.get_text(" ", strip=True)
    name = _lookup_label(pairs, COMPANY_LABELS) or _lookup_label(pairs, SELLER_LABELS)
    name_method = (
        "COMPANY_TABLE" if _lookup_label(pairs, COMPANY_LABELS) else "TRADE_TABLE" if name else ""
    )
    address = _lookup_label(pairs, ADDRESS_LABELS)
    phone = _lookup_label(pairs, PHONE_LABELS)
    business = _lookup_label(pairs, BUSINESS_LABELS)
    if not name and org.get("name"):
        name, name_method = str(org["name"]).strip(), "JSON_LD_ORGANIZATION"
    if not address:
        address_obj = org.get("address")
        if isinstance(address_obj, dict):
            address = "".join(
                str(address_obj.get(key) or "")
                for key in ("addressRegion", "addressLocality", "streetAddress")
            )
            if address:
                address_method = "JSON_LD_ADDRESS"
        if not address:
            address, address_method = site_extraction.location_text(soup, text, org)
            if address_method not in {"ADDRESS_ELEMENT", "LABELLED_ADDRESS"}:
                address = ""
    else:
        address_method = "COMPANY_TABLE"
    if not phone:
        phone = str(org.get("telephone") or site_extraction.phone(text) or "")
        phone_method = "JSON_LD_TELEPHONE" if org.get("telephone") else "PHONE_TEXT"
    else:
        phone_method = "COMPANY_TABLE"
    if name:
        name_method = name_method or "COMPANY_TABLE"
    og = soup.select_one("meta[property='og:site_name']")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if not name and og and og.get("content"):
        name, name_method = str(og["content"]).strip(), "OG_SITE_NAME"
    if not name and title:
        name = re.split(r"\s*[|｜-]\s*", title, maxsplit=1)[0].strip()
        name_method = "TITLE"
    result = {}
    for field, value, method in (
        ("company_name", name, name_method),
        ("address", address, address_method),
        ("phone", phone, phone_method),
        ("business_summary", business[:200], "BUSINESS_TABLE"),
    ):
        if value:
            result[field] = {
                "value": str(value).strip()[:200]
                if field == "business_summary"
                else str(value).strip()[:2000],
                "source_url": url,
                "method": method,
            }
    return result


def extract_company_facts(pages: list[tuple[str, str, str]]) -> dict[str, dict[str, str]]:
    priorities = {"about": 0, "trade": 1, "root": 2, "contact": 3}
    fields: dict[str, tuple[int, dict[str, str]]] = {}
    for kind, url, html in pages:
        facts = _page_facts(html, url)
        for field, fact in facts.items():
            method_priority = {
                "company_name": {
                    "COMPANY_TABLE": 0,
                    "TRADE_TABLE": 1,
                    "JSON_LD_ORGANIZATION": 2,
                    "OG_SITE_NAME": 3,
                    "TITLE": 4,
                },
                "address": {
                    "COMPANY_TABLE": 0,
                    "JSON_LD_ADDRESS": 1,
                    "ADDRESS_ELEMENT": 2,
                    "LABELLED_ADDRESS": 3,
                },
                "phone": {"COMPANY_TABLE": 0, "JSON_LD_TELEPHONE": 1, "PHONE_TEXT": 2},
                "business_summary": {"BUSINESS_TABLE": 0, "PAGE_TEXT": 1},
            }
            rank = method_priority.get(field, {}).get(fact.get("method"), 5) * 10 + priorities.get(
                kind, 4
            )
            current = fields.get(field)
            if current is None or rank < current[0]:
                fields[field] = (rank, fact)
    return {field: value[1] for field, value in fields.items()}


def _company_info_links(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    allowed_navigation = set(navigation_links(html, base_url, base_url, company_context=True))
    selected: dict[str, tuple[int, str]] = {}
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(base_url, href)
        try:
            normalized, _ = canonicalize_url(url)
        except (ValueError, UnicodeError):
            continue
        if normalized not in allowed_navigation:
            continue
        label = anchor.get_text(" ", strip=True).casefold()
        combined = f"{label} {urlsplit(url).path.casefold()}"
        kind = (
            "about"
            if any(hint in combined for hint in ABOUT_LINK_HINTS)
            else "trade"
            if any(hint in combined for hint in TRADE_LINK_HINTS)
            else ""
        )
        if not kind:
            continue
        if not same_site(base_url, normalized):
            continue
        if urlsplit(normalized).path.lower().endswith((".pdf", ".jpg", ".png", ".zip")):
            continue
        selected.setdefault(normalized, (0 if kind == "about" else 1, kind))
    ordered = sorted(selected.items(), key=lambda item: (item[1][0], item[0]))[:2]
    return [(url, value[1]) for url, value in ordered]


def _has_contact_form(html: str) -> tuple[bool, bool, bool]:
    soup = BeautifulSoup(html, "html.parser")
    external = bool(embedded_form_providers(html))
    if external:
        return False, False, True
    if any(is_contact_form(form, contact_context=True) for form in soup.select("form")):
        return True, False, False
    js_suspected = bool(custom_contact_containers(html))
    return js_suspected, js_suspected, False


def _is_listing_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = soup.get_text(" ", strip=True)
    listing_marker = re.search(
        r"加盟店一覧|掲載企業|企業一覧|会社一覧|取扱店一覧|会員企業",
        f"{title} {text}",
    )
    return bool(listing_marker and len(soup.select("a[href]")) >= 5)


def _is_blog_heavy_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    text_length = len(soup.get_text(" ", strip=True))
    article_length = sum(
        len(article.get_text(" ", strip=True)) for article in soup.select("article")
    )
    return len(soup.select("article")) >= 3 and article_length > text_length / 2


def _non_company_reasons(company_name: str, host: str, root_html: str) -> list[str]:
    pseudo_company = SimpleNamespace(
        company_name=company_name,
        domain=host,
        website_url=f"https://{host}/",
        record_type="company",
    )
    reasons = non_company_evidence(pseudo_company)
    if _is_listing_page(root_html):
        reasons.append("NON_COMPANY_LISTING_PAGE")
    return reasons


def _same_location(left: str, right: str) -> bool:
    from app.services.scraper import _extract_location

    _, left_pref, left_city = _extract_location(left)
    _, right_pref, right_city = _extract_location(right)
    return bool(left_pref and left_city and left_pref == right_pref and left_city == right_city)


def lookup_corporate_number(company_name: str, address: str) -> dict[str, str]:
    if not settings.gbizinfo_api_token:
        return {"status": "CORPORATE_CHECK_SKIPPED", "corporate_number": ""}
    try:
        with httpx.Client(timeout=settings.external_api_timeout_seconds) as client:
            response = measured_request(
                "gbizinfo",
                client.get,
                settings.gbizinfo_api_base_url.rstrip("/"),
                headers={"X-hojinInfo-api-token": settings.gbizinfo_api_token},
                params={"name": company_name, "location": address, "page": 1, "size": 20},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("form-first corporate lookup failed: type=%s", type(exc).__name__)
        return {"status": "CORPORATE_CHECK_ERROR", "corporate_number": ""}
    items = data.get("hojin-infos") or data.get("corporations") or data.get("items") or []
    matches = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate_address = str(
            item.get("location") or item.get("headOfficeLocation") or item.get("address") or ""
        )
        if address and _same_location(address, candidate_address):
            matches.append(item)
    if len(matches) == 1:
        item = matches[0]
        number = str(
            item.get("corporateNumber")
            or item.get("corporate_number")
            or item.get("hojinBango")
            or ""
        )
        if number:
            return {"status": "CORPORATE_NUMBER_MATCHED", "corporate_number": number[:20]}
        return {"status": "CORPORATE_NUMBER_NOT_FOUND", "corporate_number": ""}
    if len(matches) > 1:
        return {"status": "CORPORATE_NUMBER_AMBIGUOUS", "corporate_number": ""}
    return {"status": "CORPORATE_NUMBER_NOT_FOUND", "corporate_number": ""}


def _known_company(db, project_id, host) -> Company | None:
    normalized = host.lower().removeprefix("www.")
    return db.scalar(
        select(Company)
        .where(
            Company.project_id == project_id,
            Company.domain.in_((normalized, f"www.{normalized}")),
            Company.record_type == "company",
        )
        .order_by(Company.id)
        .limit(1)
    )


def _minimum_host_interval(host: str) -> None:
    with _HOST_GET_LOCK:
        now = time.monotonic()
        expired = [
            previous_host
            for previous_host, last_request in _HOST_LAST_GET.items()
            if now - last_request >= 1.0
        ]
        for previous_host in expired:
            _HOST_LAST_GET.pop(previous_host, None)
        wait = max(0.0, 1.0 - (now - _HOST_LAST_GET.get(host, 0.0)))
        if wait:
            time.sleep(wait)
        _HOST_LAST_GET[host] = time.monotonic()


def _fetch_candidate(contact_url: str) -> tuple[str, list[tuple[str, str, str]]]:
    fetcher = SafeFetcher()
    pages: list[tuple[str, str, str]] = []
    try:
        _minimum_host_interval(urlsplit(contact_url).hostname or "")
        fetcher.site_root = contact_url
        contact = fetcher.fetch_html(contact_url)
        if not same_site(contact_url, contact.url):
            raise ScrapeError("問い合わせページが別サイトへ転送されました。")
        pages.append(("contact", contact.url, contact.html))
        has_form, js_suspected, external = _has_contact_form(contact.html)
        if external:
            return "REJECT_EXTERNAL_FORM_SERVICE", pages
        if not has_form:
            return "NO_FORM_ON_PAGE", pages
        root_parts = urlsplit(contact.url)
        root_url = urlunsplit((root_parts.scheme, root_parts.netloc, "/", "", ""))
        if contact.url.rstrip("/") == root_url.rstrip("/"):
            root = contact
        else:
            _minimum_host_interval(root_parts.hostname or "")
            root = fetcher.fetch_html(root_url)
        if not same_site(contact.url, root.url):
            raise ScrapeError("会社トップページが別サイトへ転送されました。")
        if root.url != contact.url:
            pages.append(("root", root.url, root.html))
        if _is_listing_page(root.html):
            return "REJECT_NON_COMPANY", pages
        for url, kind in _company_info_links(root.html, root.url):
            if len(pages) >= 4:
                break
            if any(existing_url == url for _, existing_url, _ in pages):
                continue
            _minimum_host_interval(urlsplit(url).hostname or "")
            page = fetcher.fetch_html(url)
            if not same_site(root.url, page.url):
                continue
            pages.append((kind, page.url, page.html))
        return "FORM_JS_SUSPECTED" if js_suspected else "FORM_FOUND", pages
    except ScrapeError as exc:
        return "REJECT_ROBOTS" if "robots.txt" in str(exc) else "REJECT_FETCH_ERROR", pages
    finally:
        fetcher.close()


def _queue_form_analysis(db, project_id, company_ids: list) -> None:
    if not company_ids:
        return
    active = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_intelligence",
            OperationJob.status.in_(("queued", "running")),
        )
        .with_for_update()
        .limit(1)
    )
    if active:
        payload = dict(active.payload or {})
        if active.status == "queued" and payload.get("company_ids"):
            payload["company_ids"] = list(
                dict.fromkeys([*payload.get("company_ids", []), *map(str, company_ids)])
            )
        else:
            payload["form_first_company_ids"] = list(
                dict.fromkeys([*payload.get("form_first_company_ids", []), *map(str, company_ids)])
            )
        active.payload = payload
        return
    from app.services.operations import add_operation_job

    add_operation_job(
        db,
        OperationJob(
            project_id=project_id,
            operation_type="form_intelligence",
            payload={"company_ids": list(dict.fromkeys(map(str, company_ids))), "force": False},
        ),
    )


def _needs_form_analysis(db, company_id) -> bool:
    has_profile = db.scalar(
        select(FormProfile.id).where(FormProfile.company_id == company_id).limit(1)
    )
    has_unanalyzed_profile = db.scalar(
        select(FormProfile.id)
        .where(
            FormProfile.company_id == company_id,
            (FormProfile.last_analyzed_at.is_(None)) | (FormProfile.form_status == "UNANALYZED"),
        )
        .limit(1)
    )
    return has_profile is None or has_unanalyzed_profile is not None


def process_search_results(
    db, collection_job, candidates: list[Candidate], payload: dict, stopped
) -> list[Candidate]:
    query_type, industry_keyword = query_result_type(
        collection_job.keyword, payload.get("form_first_query_map") or {}
    )
    accepted: list[Candidate] = []
    known_company_ids = []
    created_hosts = []
    for result in candidates:
        if stopped():
            break
        reason = classify_search_result(db, collection_job.project_id, result)
        _record_hit(db, result, "FORM_FIRST", reason, query_type)
        if reason != "CONTACT_PAGE_CANDIDATE":
            continue
        try:
            contact_url, host = canonicalize_url(result.website_url or "")
        except (ValueError, UnicodeError):
            continue
        fetch_reason, pages = _fetch_candidate(contact_url)
        _record_hit(db, result, "FORM_FIRST", fetch_reason, query_type)
        if fetch_reason not in {"FORM_FOUND", "FORM_JS_SUSPECTED"}:
            continue
        facts = extract_company_facts(pages)
        name_fact = facts.get("company_name")
        company_name = name_fact["value"] if name_fact else host
        reasons = [] if name_fact else ["COMPANY_NAME_UNRESOLVED"]
        root_html = next((html for kind, _, html in pages if kind == "root"), pages[0][2])
        reasons.extend(_non_company_reasons(company_name, host, root_html))
        business_fact = facts.get("business_summary")
        weak_name = not name_fact or name_fact.get("method") == "TITLE"
        weak_business = not business_fact
        if weak_name and weak_business and _is_blog_heavy_page(root_html):
            reasons.append("NON_COMPANY_BLOG_ARTICLE")
        if reasons and any(item != "COMPANY_NAME_UNRESOLVED" for item in reasons):
            _record_hit(db, result, "FORM_FIRST", "REJECT_NON_COMPANY", query_type)
            continue
        existing = _known_company(db, collection_job.project_id, host)
        if existing:
            added_contact_url = not existing.contact_url
            if added_contact_url:
                existing.contact_url = contact_url
            if not existing.form_first_contact_url:
                existing.form_first_contact_url = contact_url
            if existing.reference_url == "":
                existing.reference_url = contact_url
            if _needs_form_analysis(db, existing.id):
                known_company_ids.append(existing.id)
            _record_hit(
                db,
                result,
                "FORM_FIRST",
                "REJECT_ALREADY_KNOWN",
                query_type,
                {"form_first_existing_url_added": added_contact_url},
            )
            mark_discovery(db, collection_job, result, "DUPLICATE", existing)
            continue
        identity_duplicate = duplicate_company(
            db,
            collection_job.project_id,
            Candidate(
                company_name=company_name[:500],
                website_url=urlunsplit((*urlsplit(contact_url)[:2], "/", "", "")),
                address=facts.get("address", {}).get("value", "")[:5000],
            ),
        )
        if identity_duplicate:
            added_contact_url = not identity_duplicate.contact_url
            if added_contact_url:
                identity_duplicate.contact_url = contact_url
            if not identity_duplicate.form_first_contact_url:
                identity_duplicate.form_first_contact_url = contact_url
            if _needs_form_analysis(db, identity_duplicate.id):
                known_company_ids.append(identity_duplicate.id)
            _record_hit(
                db,
                result,
                "FORM_FIRST",
                "REJECT_ALREADY_KNOWN",
                query_type,
                {"form_first_existing_url_added": added_contact_url},
            )
            mark_discovery(db, collection_job, result, "DUPLICATE", identity_duplicate)
            continue
        corporate = lookup_corporate_number(company_name, facts.get("address", {}).get("value", ""))
        _record_hit(
            db,
            result,
            "FORM_FIRST",
            fetch_reason,
            query_type,
            {"form_first_corporate_check": corporate["status"]},
        )
        if (
            payload.get("require_corporate_number")
            and corporate["status"] != "CORPORATE_NUMBER_MATCHED"
        ):
            _record_hit(db, result, "FORM_FIRST", corporate["status"], query_type)
            continue
        address = facts.get("address", {}).get("value", "")
        _, prefecture, city = _extract_location(address)
        site_discovery = {
            "discovery_method": "FORM_FIRST",
            "form_first_reasons": reasons,
            "form_first_fields": facts,
            "corporate_check": corporate["status"],
        }
        accepted.append(
            Candidate(
                company_name=company_name[:500],
                website_url=urlunsplit((*urlsplit(contact_url)[:2], "/", "", "")),
                reference_url=contact_url,
                contact_url=contact_url,
                form_first_contact_url=contact_url,
                address=address[:5000],
                phone=facts.get("phone", {}).get("value", "")[:100],
                prefecture=prefecture,
                city=city,
                business_summary=facts.get("business_summary", {}).get("value", "")[:200],
                corporate_number=corporate.get("corporate_number", ""),
                source_keyword=industry_keyword,
                collection_method="form_first",
                discovery_hit_id=result.discovery_hit_id,
                site_discovery=site_discovery,
            )
        )
        created_hosts.append(host)
        _record_hit(db, result, "FORM_FIRST", fetch_reason, query_type)
    db.flush()
    if accepted:
        for candidate in accepted:
            if candidate.website_url:
                host = canonicalize_url(candidate.website_url)[1]
                existing = _known_company(db, collection_job.project_id, host)
                if existing and not existing.contact_url:
                    existing.contact_url = candidate.contact_url
                if existing:
                    candidate.collection_method = "form_first"
                else:
                    created_hosts.append(host)
    for host in dict.fromkeys(created_hosts):
        existing = _known_company(db, collection_job.project_id, host)
        if existing:
            if _needs_form_analysis(db, existing.id):
                known_company_ids.append(existing.id)
    _queue_form_analysis(db, collection_job.project_id, list(dict.fromkeys(known_company_ids)))
    return accepted


def queue_saved_company_analysis(db, collection_job, candidates: list[Candidate]) -> None:
    hosts = {
        canonicalize_url(candidate.website_url)[1].lower().removeprefix("www.")
        for candidate in candidates
        if candidate.website_url
    }
    if not hosts:
        return
    companies = db.scalars(
        select(Company).where(
            Company.project_id == collection_job.project_id,
            Company.domain.in_(hosts | {f"www.{host}" for host in hosts}),
            Company.source == "form_first",
        )
    ).all()
    missing_profile_ids = [
        company.id for company in companies if _needs_form_analysis(db, company.id)
    ]
    _queue_form_analysis(db, collection_job.project_id, missing_profile_ids)
    if missing_profile_ids:
        db.commit()
