"""Deterministic identity comparison. A shared domain alone never confirms identity."""

import hashlib
import json
import re
import unicodedata

from app.services.collection import canonicalize_url


def normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value or "").casefold())


def identity_hash(company) -> str:
    values = [
        company.record_type,
        company.company_name,
        company.address,
        company.phone,
        company.website_url,
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def compare(existing, incoming) -> tuple[str, list[str]]:
    if existing.record_type != incoming.record_type:
        return "DIFFERENT", ["RECORD_TYPE_DIFFERENT"]
    reasons = []
    for field in ("company_name", "address", "phone"):
        a, b = normalize(getattr(existing, field)), normalize(getattr(incoming, field))
        if not a or not b:
            continue
        if a == b:
            if field == "address" and not re.search(r"\d", a):
                reasons.append("REGION_ONLY")
            elif field == "phone" and len(a) < 9:
                continue
            else:
                reasons.append(field.upper() + "_MATCH")
        elif field in {"address", "phone"}:
            return "REVIEW_REQUIRED", [field.upper() + "_CONFLICT"]
    if existing.website_url and incoming.website_url:
        if canonicalize_url(existing.website_url)[1] == canonicalize_url(incoming.website_url)[1]:
            reasons.append("DOMAIN_MATCH")
    name = "COMPANY_NAME_MATCH" in reasons
    if name and ("ADDRESS_MATCH" in reasons or "PHONE_MATCH" in reasons):
        return "CONFIRMED", reasons
    if len(reasons) >= 2:
        return "PROBABLE", reasons
    return "REVIEW_REQUIRED", reasons or ["INSUFFICIENT_IDENTITY_EVIDENCE"]


def website_match(company, data) -> tuple[str, list[str]]:
    text = normalize(data.website_text)
    name, address = normalize(company.company_name), normalize(company.address)
    reasons = []
    if len(name) >= 4 and name in text:
        reasons.append("COMPANY_NAME_MATCH")
    if re.search(r"\d", address) and address in text:
        reasons.append("ADDRESS_MATCH")
    phone = normalize(company.phone)
    if len(phone) >= 9 and phone == normalize(data.phone):
        reasons.append("PHONE_MATCH")
    confirmed = "COMPANY_NAME_MATCH" in reasons and any(
        r in reasons for r in ("ADDRESS_MATCH", "PHONE_MATCH")
    )
    return ("CONFIRMED" if confirmed else "REVIEW_REQUIRED"), reasons


def site_queries(company) -> list[str]:
    # No hard-coded industry dictionary or unbounded region expansion.
    values = [f"{company.company_name} {company.address} 公式サイト"]
    if company.phone:
        values.append(f"{company.company_name} {company.phone} 公式")
    values.append(f"{company.company_name} {company.city or company.prefecture} 公式")
    return list(dict.fromkeys(" ".join(value.split()) for value in values))[:3]
