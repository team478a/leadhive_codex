"""Read-only, deterministic evaluation. UNKNOWN is never a positive fact."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import ExternalPresenceSearch, LeadSiteEvidence
from app.schema_collection_conditions import CollectionCondition
from app.services.external_presence import inventory
from app.services.lead_identity import identity_hash
from app.services.site_identity_review import latest, state


def snapshot_hash(snapshot: dict) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def classification(results: list[dict]) -> str:
    if any(
        (r["priority"] == "MUST" and r["outcome"] == "NO_MATCH")
        or (r["priority"] == "EXCLUDE" and r["outcome"] == "MATCH")
        for r in results
    ):
        return "NO_MATCH"
    if any(r["priority"] in {"MUST", "EXCLUDE"} and r["outcome"] == "UNKNOWN" for r in results):
        return "REVIEW_REQUIRED"
    return "MATCH"


def evaluate(db, company, conditions: list[CollectionCondition], now=None):
    now = now or datetime.now(timezone.utc)
    fresh_after = now - timedelta(hours=24)
    presences = {r["platform"]: r for r in inventory(db, company.id)}
    results = []
    for condition in conditions:
        outcome, reason, evidence_url, observed_at = "UNKNOWN", "VERIFICATION_UNSUPPORTED", "", None
        if condition.type == "MEDIA_EXISTS":
            presence = presences[condition.value]
            evidence_url, observed_at = presence["url"], presence["observed_at"]
            reason = presence["reason"] or presence["status"]
            if presence["status"] == "FOUND":
                if observed_at is not None and observed_at >= fresh_after:
                    outcome, reason = "MATCH", "PRESENCE_FOUND"
                else:
                    reason = "EVIDENCE_EXPIRED"
            elif presence["status"] == "NOT_FOUND" and presence["reason"] == "SEARCH_NO_MATCH":
                attempt = db.scalar(
                    select(ExternalPresenceSearch)
                    .where(
                        ExternalPresenceSearch.company_id == company.id,
                        ExternalPresenceSearch.platform == condition.value,
                        ExternalPresenceSearch.status == "COMPLETED",
                    )
                    .order_by(ExternalPresenceSearch.created_at.desc())
                    .limit(1)
                )
                # NOT_FOUND without a completed fresh investigation is not proof of absence.
                if attempt is not None and attempt.created_at >= fresh_after:
                    outcome, reason, observed_at = "NO_MATCH", "SEARCH_NO_MATCH", attempt.created_at
                else:
                    reason = "NEGATIVE_EVIDENCE_UNAVAILABLE"
        elif condition.type == "OFFICIAL_SITE":
            automatic = db.scalar(
                select(LeadSiteEvidence)
                .where(
                    LeadSiteEvidence.company_id == company.id,
                    LeadSiteEvidence.confidence == "CONFIRMED",
                    LeadSiteEvidence.identity_hash == identity_hash(company),
                    LeadSiteEvidence.observed_at >= fresh_after,
                )
                .order_by(LeadSiteEvidence.observed_at.desc())
                .limit(1)
            )
            human = latest(db, company.id)
            human_current = (
                human is not None
                and state(human, identity_hash(company), now) == "CURRENT"
                and human.created_at >= fresh_after
            )
            if automatic is not None or human_current:
                outcome, reason, evidence_url = (
                    "MATCH",
                    "OFFICIAL_SITE_CONFIRMED",
                    company.website_url,
                )
                observed_at = automatic.observed_at if automatic is not None else human.created_at
            else:
                reason = "OFFICIAL_SITE_UNCONFIRMED"
        results.append(
            dict(
                id=condition.id,
                priority=condition.priority,
                type=condition.type,
                value=condition.value,
                outcome=outcome,
                reason=reason,
                evidence_url=evidence_url,
                observed_at=observed_at,
            )
        )
    return dict(
        company_id=company.id,
        company_name=company.company_name,
        state=classification(results),
        conditions=results,
        want_matched=sum(r["priority"] == "WANT" and r["outcome"] == "MATCH" for r in results),
        want_unknown=sum(r["priority"] == "WANT" and r["outcome"] == "UNKNOWN" for r in results),
    )
