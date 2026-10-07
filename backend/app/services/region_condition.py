"""Read-only address predicates; never infer a service area from a keyword."""

import re
import unicodedata
from datetime import timedelta

from sqlalchemy import select

from app.models import LeadSiteEvidence
from app.services.lead_identity import identity_hash, normalize
from app.services.scraper import PREFECTURES
from app.services.site_identity_review import latest, official_evidence_url, state


def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def compare_region(company, value):
    """Only qualified prefecture/municipality labels; no fuzzy substring matching."""
    target = compact(value)
    pref = next((p for p in PREFECTURES if target.startswith(p)), None)
    if pref is None:
        return "UNKNOWN", "REGION_PREFECTURE_REQUIRED"
    suffix = target[len(pref) :]
    if suffix.startswith("/"):
        suffix = suffix[1:]
    if re.search(r"または|もしくは|かつ|および|及び|[と・,+]|\b(?:OR|AND)\b", suffix, re.I):
        return "UNKNOWN", "REGION_FORMAT_UNSUPPORTED"
    if suffix and not re.fullmatch(r"[^0-9/、,と]+(?:市|区|町|村)", suffix):
        return "UNKNOWN", "REGION_FORMAT_UNSUPPORTED"
    # The structured fields must agree with the beginning of the verified full address.
    current_pref, city, address = (
        compact(company.prefecture),
        compact(company.city),
        compact(company.address),
    )
    if current_pref not in PREFECTURES or not city or not address.startswith(current_pref + city):
        return "UNKNOWN", "REGION_ADDRESS_CONFLICT"
    if not re.search(r"[0-9]", address) or not re.fullmatch(r"[^0-9/、,]+(?:市|区|町|村)", city):
        return "UNKNOWN", "REGION_ADDRESS_INCOMPLETE"
    if address[len(current_pref + city) :].startswith(("市", "区", "町", "村")):
        return "UNKNOWN", "REGION_ADDRESS_INCOMPLETE"
    if pref != current_pref:
        return "NO_MATCH", "VERIFIED_REGION_DIFFERENT"
    if not suffix or suffix == city:
        return "MATCH", "VERIFIED_REGION_MATCH"
    if suffix.startswith(city) or city.startswith(suffix):
        return "UNKNOWN", "REGION_FORMAT_UNSUPPORTED"
    # A city boundary is explicit. Unknown wards / towns within a city are not excluded.
    if suffix.endswith("市") and city.endswith("市"):
        return "NO_MATCH", "VERIFIED_REGION_DIFFERENT"
    return "UNKNOWN", "REGION_FORMAT_UNSUPPORTED"


def evaluate_region(db, company, value, now):
    unknown = dict(
        outcome="UNKNOWN", reason="REGION_ADDRESS_UNVERIFIED", evidence_url="", observed_at=None
    )
    digest = identity_hash(company)
    fresh = now - timedelta(hours=24)
    human = latest(db, company.id)
    source, observed = "", None
    if human is not None:
        if (
            human.project_id != company.project_id
            or state(human, digest, now) != "CURRENT"
            or not fresh <= human.created_at <= now
        ):
            return unknown
        if "ADDRESS_MATCH" not in human.reasons or normalize(human.observed_address) != normalize(
            company.address
        ):
            return unknown
        source, observed = human.source_url, human.created_at
    else:
        # Chain websites do not prove which location an address belongs to.
        if company.record_type == "location":
            return {**unknown, "reason": "REGION_LOCATION_REVIEW_REQUIRED"}
        evidence = db.scalar(
            select(LeadSiteEvidence)
            .where(
                LeadSiteEvidence.company_id == company.id,
                LeadSiteEvidence.identity_hash == digest,
            )
            .order_by(LeadSiteEvidence.observed_at.desc(), LeadSiteEvidence.id.desc())
            .limit(1)
        )
        if (
            evidence is None
            or evidence.confidence != "CONFIRMED"
            or not fresh <= evidence.observed_at <= now
        ):
            return unknown
        if not {"ADDRESS_MATCH", "COMPANY_NAME_MATCH"} <= set(evidence.reasons):
            return unknown
        # Retained evidence alone cannot survive changed/removed website text.
        if normalize(company.address) not in normalize(company.website_text) or normalize(
            company.company_name
        ) not in normalize(company.website_text):
            return unknown
        source, observed = evidence.source_url, evidence.observed_at
    try:
        source = official_evidence_url(company, source)
    except (ValueError, UnicodeError):
        return unknown
    outcome, reason = compare_region(company, value)
    return dict(outcome=outcome, reason=reason, evidence_url=source, observed_at=observed)
