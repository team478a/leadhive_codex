"""Human fact verification is separate from AI guesses and target keywords."""

import hashlib
import json
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import CollectionFactReview
from app.services.lead_identity import identity_hash


def predicate_value(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def company_hash(company):
    # Hash only; do not copy website text or AI output into the review ledger.
    fields = [
        identity_hash(company),
        company.prefecture,
        company.city,
        company.business_type,
        company.business_summary,
        company.website_text,
        company.reference_url,
    ]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def latest(db, company, kind, value):
    return db.scalar(
        select(CollectionFactReview)
        .where(
            CollectionFactReview.company_id == company.id,
            CollectionFactReview.project_id == company.project_id,
            CollectionFactReview.condition_type == kind,
            CollectionFactReview.value == predicate_value(value),
        )
        .order_by(CollectionFactReview.version.desc())
        .limit(1)
    )


def result(db, company, kind, value, now=None, *, include_review_hints=True):
    now = now or datetime.now(timezone.utc)
    row = latest(db, company, kind, value)
    outcome, reason = "UNKNOWN", "FACT_REVIEW_REQUIRED"
    if row:
        if row.company_hash != company_hash(company):
            reason = "ENTITY_CHANGED"
        elif row.outcome == "UNKNOWN":
            reason = "FACT_REVIEW_WITHDRAWN"
        elif row.expires_at <= now:
            reason = "EVIDENCE_EXPIRED"
        elif row.created_at > now:
            reason = "EVIDENCE_FUTURE"
        else:
            outcome, reason = row.outcome, "HUMAN_FACT_VERIFIED"
    automatic = {}
    if row is None and kind == "AREA":
        from app.services.region_condition import evaluate_region

        automatic = evaluate_region(db, company, value, now)
        outcome, reason = automatic["outcome"], automatic["reason"]
    review_hints = {}
    if kind == "INDUSTRY" and include_review_hints:
        from app.services.industry_review_hints import hints

        review_hints["review_hints"] = hints(db, company, value, now)
    return dict(
        outcome=outcome,
        reason=reason,
        evidence_url=row.source_url if row else automatic.get("evidence_url", ""),
        observed_at=row.created_at if row else automatic.get("observed_at"),
        review_version=row.version if row else 0,
        company_fact_hash=company_hash(company),
        evidence_excerpt=row.evidence_excerpt if row else "",
        observed_value=company.address if kind == "AREA" else company.business_type,
        **review_hints,
    )
