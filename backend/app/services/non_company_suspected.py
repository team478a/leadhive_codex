import re
from urllib.parse import urlsplit

PUBLIC_HOST_SUFFIXES = (".lg.jp", ".go.jp", ".ed.jp", ".ac.jp")
PUBLIC_HOST_PREFIXES = ("city.", "pref.", "town.", "vill.")
ARTICLE_NAME_PATTERNS = (
    re.compile(r"[0-9０-９]+年版"),
    re.compile(r"年度"),
    re.compile(r"調べてみた"),
    re.compile(r"がスタート"),
    re.compile(r"開催"),
    re.compile(r"募集"),
    re.compile(r"とは"),
    re.compile(r"[｜|]\s*[^｜|]*(?:都|道|府|県|市|区|町|村)$"),
)


def _host(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    try:
        host = urlsplit(raw if "://" in raw else f"//{raw}").hostname or ""
    except ValueError:
        return ""
    return host.rstrip(".").casefold()


def _hosts(company) -> set[str]:
    return {
        host for host in (_host(company.domain or ""), _host(company.website_url or "")) if host
    }


def evidence(company) -> list[str]:
    name = (company.company_name or "").strip()
    reasons = []
    if getattr(company, "record_type", "company") == "location":
        reasons.append("NON_COMPANY_LOCATION_RECORD")
    if not name or re.fullmatch(r"[-—]+", name):
        reasons.append("NON_COMPANY_NAME_MISSING")

    if any(
        host.endswith(PUBLIC_HOST_SUFFIXES) or host.startswith(PUBLIC_HOST_PREFIXES)
        for host in _hosts(company)
    ):
        reasons.append("NON_COMPANY_PUBLIC_DOMAIN")

    if name and (
        name.startswith(("»", "・", "【"))
        or len(name) > 40
        or any(pattern.search(name) for pattern in ARTICLE_NAME_PATTERNS)
    ):
        reasons.append("NON_COMPANY_ARTICLE_STYLE_NAME")
    return reasons


def display_name(company) -> str:
    name = (company.company_name or "").strip()
    if name and not re.fullmatch(r"[-—]+", name):
        return name
    return _host(company.domain or "") or _host(company.website_url or "") or "—"


def current_suspected_evidence(db, companies) -> dict:
    from app.services.collection_feedback import latest_company_feedbacks

    candidates = [
        company for company in companies if evidence(company) or company.status == "excluded"
    ]
    feedback_by_company = latest_company_feedbacks(db, candidates)
    suspected = {}
    for company in companies:
        reasons = evidence(company)
        feedback = feedback_by_company.get(company.id)
        if (
            feedback
            and feedback.get("outcome") == "OK"
            and feedback.get("reason") == "company_verified"
        ):
            continue
        if (
            feedback
            and feedback.get("outcome") == "NG"
            and feedback.get("reason") == "wrong_company"
        ):
            reasons.insert(0, "NON_COMPANY_REVIEW_NG")
        if reasons:
            suspected[company.id] = list(dict.fromkeys(reasons))
    return suspected
