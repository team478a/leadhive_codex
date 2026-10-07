"""Current site evidence for collection criteria; human withdrawal always wins."""

from datetime import timedelta

from sqlalchemy import select

from app.models import LeadSiteEvidence
from app.services.lead_identity import identity_hash
from app.services.site_identity_review import latest, official_evidence_url, state


def evaluate_site(db, company, now):
    result = dict(
        outcome="UNKNOWN", reason="OFFICIAL_SITE_UNCONFIRMED", evidence_url="", observed_at=None
    )
    digest = identity_hash(company)
    cutoff = now - timedelta(hours=24)
    human = latest(db, company.id)
    if human is not None:
        current = state(human, digest, now)
        if human.project_id != company.project_id:
            return result
        if current != "CURRENT":
            return {**result, "reason": "SITE_REVIEW_" + current}
        if not cutoff <= human.created_at <= now:
            return {
                **result,
                "reason": "EVIDENCE_EXPIRED" if human.created_at < cutoff else "EVIDENCE_FUTURE",
            }
        source, observed = human.source_url, human.created_at
    else:
        evidence = db.scalar(
            select(LeadSiteEvidence)
            .where(LeadSiteEvidence.company_id == company.id)
            .order_by(LeadSiteEvidence.observed_at.desc(), LeadSiteEvidence.id.desc())
            .limit(1)
        )
        if evidence is None or evidence.confidence != "CONFIRMED":
            return result
        if evidence.identity_hash != digest:
            return {**result, "reason": "ENTITY_CHANGED"}
        if not cutoff <= evidence.observed_at <= now:
            return {
                **result,
                "reason": "EVIDENCE_EXPIRED"
                if evidence.observed_at < cutoff
                else "EVIDENCE_FUTURE",
            }
        source, observed = evidence.source_url, evidence.observed_at
    try:
        source = official_evidence_url(company, source)
    except (ValueError, UnicodeError):
        return {**result, "reason": "SITE_EVIDENCE_URL_INVALID"}
    return dict(
        outcome="MATCH", reason="OFFICIAL_SITE_CONFIRMED", evidence_url=source, observed_at=observed
    )
