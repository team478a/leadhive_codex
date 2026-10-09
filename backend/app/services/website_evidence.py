"""Persist observations separately from the immutable raw discovery ledger."""

import hashlib
import json

from sqlalchemy import or_, select

from app.models import LeadSiteEvidence, LeadSourceObservation
from app.services.lead_identity import identity_hash


def record(db, company, data, url, before_hash, confidence, reasons, applied):
    current_hash = identity_hash(company)
    derived = db.scalar(
        select(LeadSiteEvidence.id)
        .where(
            LeadSiteEvidence.company_id == company.id,
            or_(
                LeadSiteEvidence.reasons.contains(["IDENTITY_CHANGED_DURING_EXTRACTION"]),
                LeadSiteEvidence.reasons.contains(["IDENTITY_DERIVED_FROM_EXTRACTION"]),
            ),
        )
        .limit(1)
    )
    if confidence == "CONFIRMED" and derived:
        # Running the same scraper twice is not independent identity verification.
        # Human site/identity review remains the existing explicit confirmation path.
        confidence = "REVIEW_REQUIRED"
        reasons = [*reasons, "IDENTITY_DERIVED_FROM_EXTRACTION"]
    if current_hash != before_hash:
        confidence = "REVIEW_REQUIRED"
        reasons = [*reasons, "IDENTITY_CHANGED_DURING_EXTRACTION"]
    db.add(
        LeadSiteEvidence(
            company_id=company.id,
            source_url=url,
            identity_hash=before_hash,
            confidence=confidence,
            reasons=reasons or ["INSUFFICIENT_IDENTITY_EVIDENCE"],
        )
    )
    # Associate with an existing source operation; do not invent a raw discovery.
    source = db.scalar(
        select(LeadSourceObservation)
        .where(LeadSourceObservation.company_id == company.id)
        .order_by(LeadSourceObservation.observed_at.desc(), LeadSourceObservation.id)
        .limit(1)
    )
    if source is None:
        return
    facts = {
        name: {**evidence, "confidence": 0, "protected": name in (company.protected_fields or [])}
        for name, evidence in data.field_evidence.items()
    }
    facts["crawl_errors"] = data.crawl_errors
    digest = hashlib.sha256(
        json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if db.scalar(
        select(LeadSourceObservation.id).where(
            LeadSourceObservation.company_id == company.id,
            LeadSourceObservation.collection_job_id == source.collection_job_id,
            LeadSourceObservation.observation_hash == digest,
        )
    ):
        return
    db.add(
        LeadSourceObservation(
            company_id=company.id,
            collection_job_id=source.collection_job_id,
            source="website",
            source_url=url,
            observation_hash=digest,
            identity_status=confidence,
            identity_reasons=reasons,
            facts=facts,
            applied_fields=applied,
        )
    )
