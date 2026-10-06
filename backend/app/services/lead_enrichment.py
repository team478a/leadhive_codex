"""Retain duplicate observations and fill only missing, unprotected fields."""

import hashlib
import json

from sqlalchemy import select

from app.models import LeadSourceObservation
from app.services.lead_identity import compare

FIELDS = ("company_name", "address", "phone", "email", "website_url", "reference_url")
TERMS = {
    "google_places": (
        "https://developers.google.com/maps/documentation/places/web-service/policies",
        "Google Maps attribution; storage restrictions apply",
    ),
    "serper": ("https://serper.dev/terms", "Check originating site usage rights"),
    "gbizinfo": ("https://info.gbiz.go.jp/", "Check current gBizINFO terms before expanded reuse"),
    "csv": ("", "Customer must hold data usage rights"),
    "url": ("", "Website terms and robots apply"),
}


def observe_candidate(db, job, company, candidate, *, new=False):
    values = {field: getattr(candidate, field) for field in FIELDS}
    digest = hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if db.scalar(
        select(LeadSourceObservation.id).where(
            LeadSourceObservation.collection_job_id == job.id,
            LeadSourceObservation.company_id == company.id,
            LeadSourceObservation.observation_hash == digest,
        )
    ):
        return
    state, reasons = (
        ("PROBABLE", ["SINGLE_SOURCE_DISCOVERY"]) if new else compare(company, candidate)
    )
    applied = []
    # Places content is not copied into a second persistent evidence store.
    # Other external source reuse remains a review candidate, not a confirmed overwrite.
    usage = "CUSTOMER_SUPPLIED" if job.source in {"csv", "url"} else "REVIEW_REQUIRED"
    if state == "CONFIRMED" and usage == "CUSTOMER_SUPPLIED":
        for field in ("phone", "email", "address", "reference_url"):
            value = values[field]
            if (
                value
                and not getattr(company, field)
                and field not in (company.protected_fields or [])
            ):
                setattr(company, field, value)
                applied.append(field)
    protected = set(company.protected_fields or [])
    facts = (
        {
            field: {
                "value": value,
                "confidence": 50,
                "verified": False,
                "protected": field in protected,
            }
            for field, value in values.items()
            if value
        }
        if job.source in {"csv", "url"}
        else {}
    )
    terms, attribution = TERMS[job.source]
    db.add(
        LeadSourceObservation(
            company_id=company.id,
            collection_job_id=job.id,
            source=job.source,
            source_url=(candidate.reference_url or candidate.website_url or "") if facts else "",
            terms_reference=terms,
            allowed_usage=usage,
            attribution_requirement=attribution,
            observation_hash=digest,
            identity_status=state,
            identity_reasons=reasons,
            facts=facts,
            applied_fields=applied,
        )
    )
