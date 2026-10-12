"""Minimal frozen field provenance in Activity; never grants delivery permission."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from app.config import settings
from app.models import Activity, SiteIdentityReviewEvent
from app.services.feedback_provenance import digest
from app.services.lead_identity import identity_hash

PREFIX = "[field-feedback-v1] "


def public_url(value):
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None
    except ValueError:
        return None
    return value


def versions(*files):
    root = Path(__file__).parent
    source_hash = digest({name: (root / name).read_text(encoding="utf-8") for name in files})
    return {"model": None, "prompt": None, "rule": source_hash, "code": source_hash}


def save(db, company, value):
    value.update(company_id=str(company.id), project_id=str(company.project_id))
    db.add(Activity(company_id=company.id, activity_type="note", note=PREFIX + json.dumps(value)))


def web_binding(company):
    return digest(
        [
            str(company.project_id),
            identity_hash(company),
            company.website_url,
            company.contact_url,
            company.scraped_at.isoformat() if company.scraped_at else None,
        ]
    )


def capture_web(db, company):
    if not settings.feedback_provenance_enabled:
        return
    save(
        db,
        company,
        {
            "kind": "WEB_DECISION",
            "binding": web_binding(company),
            "observed_at": company.scraped_at.isoformat(),
            "website_url": public_url(company.website_url),
            "contact_url": public_url(company.contact_url),
            "versions": versions("scraper.py", "contact_discovery.py", "site_extraction.py"),
        },
    )


def bound_web(db, company):
    rows = db.scalars(
        select(Activity)
        .where(
            Activity.company_id == company.id,
            Activity.note.startswith(PREFIX),
            Activity.note.contains('"binding": "' + web_binding(company) + '"'),
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(1)
    ).all()
    for row in rows:
        value = json.loads(row.note[len(PREFIX) :])
        if value.get("kind") == "WEB_DECISION" and value.get("binding") == web_binding(company):
            return value
    return None


def capture_site_review(db, company, review):
    if not settings.feedback_provenance_enabled:
        return
    db.flush()
    original = bound_web(db, company)
    save(
        db,
        company,
        {
            "kind": "SITE_REVIEW",
            "review_id": str(review.id),
            "original": original,
            "reviewed_official_url": public_url(company.website_url)
            if review.event_type == "CONFIRMED"
            else None,
        },
    )


def capture_form(db, company, profile):
    if not settings.feedback_provenance_enabled:
        return
    snapshot = {
        "form_url": public_url(profile.form_url),
        "fingerprint": profile.fingerprint,
        "form_status": profile.form_status,
        "sales_contact_status": profile.sales_contact_status,
        "captcha_type": profile.captcha_type,
        "form_found": profile.form_found,
        "delivery_supported": profile.delivery_supported,
        "confirmation_page": profile.confirmation_page,
        "safety_blocked": True,
    }
    save(
        db,
        company,
        {
            "kind": "FORM_DIAGNOSTIC",
            "profile_id": str(profile.id),
            "observed_at": profile.last_analyzed_at.isoformat(),
            "snapshot": snapshot,
            "snapshot_hash": digest(snapshot),
            "versions": versions("form_intelligence/analyzer.py", "form_intelligence/rules.py"),
            "analysis_version": profile.analysis_version,
            "provider": profile.analysis_provider,
            "duration_ms": profile.analysis_duration_ms,
        },
    )


def supplemental_records(db, project_id, safe_url):
    """Legacy site roots/predictions remain unknown; never join to current mutable URLs."""
    from app.models import Company

    rows = db.execute(
        select(Activity, Company)
        .join(Company, Company.id == Activity.company_id)
        .where(Company.project_id == project_id, Activity.note.startswith(PREFIX))
        .order_by(Activity.created_at, Activity.id)
        .limit(1001)
    ).all()
    if len(rows) > 1000:
        raise OverflowError("Export limit exceeded")
    companions = {}
    records = []
    for activity, company in rows:
        value = json.loads(activity.note[len(PREFIX) :])
        if value.get("project_id") != str(project_id) or value.get("company_id") != str(company.id):
            continue
        if value.get("kind") == "SITE_REVIEW":
            companions[value["review_id"]] = value
        elif value.get("kind") == "FORM_DIAGNOSTIC":
            if value.get("snapshot_hash") != digest(value["snapshot"]):
                raise ValueError("Diagnostic integrity mismatch")
            snapshot = dict(value["snapshot"])
            snapshot["form_url"] = safe_url(snapshot["form_url"])
            records.append(
                {
                    "source": "form_diagnostic",
                    "source_id": str(activity.id),
                    "company_id": str(company.id),
                    "project_id": str(project_id),
                    "entity_key": str(company.id),
                    "field": "form_analysis",
                    "principal": "SYSTEM",
                    "observed_at": value["observed_at"],
                    "snapshot_observed_at": value["observed_at"],
                    "snapshot": snapshot,
                    "snapshot_hash": digest(snapshot),
                    "prediction": snapshot["form_status"],
                    "versions": value["versions"],
                    "payload": {"reason": "diagnostic"},
                    "evidence_reference": "activity:" + str(activity.id),
                    "analysis_version": value["analysis_version"],
                    "provider": value["provider"],
                    "duration_ms": value["duration_ms"],
                    "estimated_cost": None,
                }
            )
    reviews = db.scalars(
        select(SiteIdentityReviewEvent)
        .where(SiteIdentityReviewEvent.project_id == project_id)
        .order_by(SiteIdentityReviewEvent.created_at, SiteIdentityReviewEvent.id)
        .limit(1001)
    ).all()
    if len(reviews) + len(records) > 1000:
        raise OverflowError("Export limit exceeded")
    for row in reviews:
        companion = companions.get(str(row.id), {})
        original = companion.get("original") or {}
        candidate = safe_url(original.get("website_url"))
        snapshot = {
            "original_official_url": candidate,
            "identity_hash": row.identity_hash,
            "safety_blocked": True,
        }
        records.append(
            {
                "source": "site_identity_review",
                "source_id": str(row.id),
                "company_id": str(row.company_id),
                "project_id": str(project_id),
                "entity_key": str(row.company_id),
                "principal": "HUMAN",
                "observed_at": row.created_at.isoformat(),
                "snapshot_observed_at": original.get("observed_at") or row.created_at.isoformat(),
                "snapshot": snapshot,
                "snapshot_hash": digest(snapshot),
                "prediction": candidate,
                "versions": original.get("versions")
                or dict.fromkeys(("model", "prompt", "rule", "code")),
                "reviewed_official_url": safe_url(companion.get("reviewed_official_url")),
                "payload": {
                    "actor_user_id": str(row.actor_user_id),
                    "event_type": row.event_type,
                    "evidence_url": safe_url(row.source_url),
                },
                "evidence_reference": "site_identity_review:" + str(row.id),
                "evidence_text_redacted": True,
            }
        )
    return records
