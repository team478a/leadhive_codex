"""Human observed identity facts plus existing deterministic site evidence."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select

from app.models import LeadSiteEvidence, SiteIdentityReviewEvent
from app.services.collection import canonicalize_url
from app.services.contact_destinations import normalize_destination
from app.services.lead_identity import identity_hash


def official_evidence_url(company, value):
    parsed = urlsplit(value)
    source = normalize_destination("form", value)
    if (
        parsed.query
        or parsed.fragment
        or canonicalize_url(source)[1] != canonicalize_url(company.website_url)[1]
    ):
        raise ValueError("Evidence must be a public official-site URL")
    return source


def latest(db, company_id):
    return db.scalar(
        select(SiteIdentityReviewEvent)
        .where(SiteIdentityReviewEvent.company_id == company_id)
        .order_by(SiteIdentityReviewEvent.version.desc())
        .limit(1)
    )


def state(row, digest, now=None):
    now = now or datetime.now(timezone.utc)
    if row is None:
        return "UNREVIEWED"
    if row.event_type == "REVOKED":
        return "REVOKED"
    if row.expires_at <= now:
        return "EXPIRED"
    return "CURRENT" if row.identity_hash == digest else "STALE"


def public_review(row, company, now=None):
    return dict(
        state=state(row, identity_hash(company), now),
        version=row.version if row else 0,
        actor_user_id=row.actor_user_id if row else None,
        created_at=row.created_at if row else None,
        expires_at=row.expires_at if row else None,
        source_url=row.source_url if row else "",
        observed_name=row.observed_name if row else "",
        observed_address=row.observed_address if row else "",
        observed_phone=row.observed_phone if row else "",
        evidence_excerpt=row.evidence_excerpt if row else "",
        reasons=row.reasons if row else [],
    )


def confirmation(db, company, now=None):
    automatic = db.scalar(
        select(LeadSiteEvidence.id)
        .where(
            LeadSiteEvidence.company_id == company.id,
            LeadSiteEvidence.confidence == "CONFIRMED",
            LeadSiteEvidence.identity_hash == identity_hash(company),
        )
        .limit(1)
    )
    if automatic is not None:
        return "AUTOMATIC_RULE"
    if state(latest(db, company.id), identity_hash(company), now) == "CURRENT":
        return "HUMAN_OBSERVED"
    return None
