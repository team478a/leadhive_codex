"""Read-only, deterministic evaluation. UNKNOWN is never a positive fact."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import ExternalPresenceSearch
from app.schema_collection_conditions import CollectionCondition
from app.services.external_presence import inventory
from app.services.official_site_condition import evaluate_site


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


def evaluate(
    db, company, conditions: list[CollectionCondition], now=None, *, include_review_hints=True
):
    now = now or datetime.now(timezone.utc)
    fresh_after = now - timedelta(hours=24)
    presences = {r["platform"]: r for r in inventory(db, company.id)}
    results = []
    for condition in conditions:
        review = {}
        outcome, reason, evidence_url, observed_at = "UNKNOWN", "VERIFICATION_UNSUPPORTED", "", None
        if condition.type in {"AREA", "INDUSTRY"}:
            from app.services.collection_fact_reviews import result

            review = result(
                db,
                company,
                condition.type,
                condition.value,
                now,
                include_review_hints=include_review_hints,
            )
            outcome, reason = review["outcome"], review["reason"]
            evidence_url, observed_at = review["evidence_url"], review["observed_at"]
        elif condition.type == "MEDIA_EXISTS":
            presence = presences[condition.value]
            evidence_url, observed_at = presence["url"], presence["observed_at"]
            reason = presence["reason"] or presence["status"]
            if presence["status"] == "FOUND":
                if observed_at is not None and fresh_after <= observed_at <= now:
                    outcome, reason = "MATCH", "PRESENCE_FOUND"
                else:
                    reason = (
                        "EVIDENCE_FUTURE"
                        if observed_at is not None and observed_at > now
                        else "EVIDENCE_EXPIRED"
                    )
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
                if attempt is not None and fresh_after <= attempt.created_at <= now:
                    outcome, reason, observed_at = "NO_MATCH", "SEARCH_NO_MATCH", attempt.created_at
                else:
                    reason = "NEGATIVE_EVIDENCE_UNAVAILABLE"
        elif condition.type == "OFFICIAL_SITE":
            proof = evaluate_site(db, company, now)
            outcome, reason = proof["outcome"], proof["reason"]
            evidence_url, observed_at = proof["evidence_url"], proof["observed_at"]
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
                **{
                    k: review[k]
                    for k in (
                        "review_version",
                        "company_fact_hash",
                        "evidence_excerpt",
                        "observed_value",
                        "review_hints",
                    )
                    if k in review
                },
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
