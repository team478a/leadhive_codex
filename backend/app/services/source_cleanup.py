"""Reversible system source cleanup; never Human Truth or contact permission."""

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Activity, AiReview
from app.services.collection import canonicalize_url
from app.services.collection_discovery import THIRD_PARTY_DOMAINS
from app.services.collection_feedback import decode
from app.services.source_exclusions import domains

PREFIX = "[source-cleanup-v1] "


def event_value(note):
    if not note.startswith(PREFIX):
        return None
    try:
        value = json.loads(note[len(PREFIX) :])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def history(db, company_id):
    return db.scalars(
        select(Activity)
        .where(Activity.company_id == company_id)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
    ).all()


def latest_event(db, company_id):
    return next(
        (value for row in history(db, company_id) if (value := event_value(row.note)) is not None),
        None,
    )


def known_source(url, project_domains):
    try:
        _, host = canonicalize_url(url or "")
    except (ValueError, UnicodeError):
        return None
    if host.removeprefix("www.") in project_domains or any(
        host == domain or host.endswith("." + domain) for domain in THIRD_PARTY_DOMAINS
    ):
        return host
    return None


def cleanup(db, project_id, companies, actor_id):
    project_domains = domains(db, project_id)
    moved, protected = [], []
    for company in companies:
        # A portal reference attached to a real Location must not exclude the business.
        if company.record_type != "company" or company.source != "serper":
            continue
        host = known_source(company.website_url, project_domains)
        if not host or company.status == "excluded":
            continue
        rows = history(db, company.id)
        last = next((value for row in rows if (value := event_value(row.note)) is not None), None)
        human_review = (
            any((value := decode(row.note)) and value.get("subject") == "company" for row in rows)
            or db.scalar(select(AiReview.id).where(AiReview.company_id == company.id)) is not None
        )
        if (
            company.status != "unreviewed"
            or human_review
            or any(row.activity_type == "status_change" for row in rows)
            or company.protected_fields
            or company.do_not_contact
            or company.exclusion_reason
            or company.contact_quality_status == "verified"
            or (
                last
                and last.get("action") == "RESTORE"
                and last.get("website_url") == company.website_url
            )
        ):
            protected.append(str(company.id))
            continue
        now = datetime.now(timezone.utc)
        event = dict(
            action="EXCLUDE",
            company_id=str(company.id),
            project_id=str(project_id),
            actor_user_id=str(actor_id),
            origin="SYSTEM_RULE",
            domain=host,
            website_url=company.website_url,
            previous_status=company.status,
            previous_do_not_contact=company.do_not_contact,
            previous_exclusion_reason=company.exclusion_reason,
            after_updated_at=now.isoformat(),
            rule_version="known-media-v1",
        )
        company.status = "excluded"
        # Reuse the existing send guard, including already queued deliveries.
        company.do_not_contact = True
        company.exclusion_reason = "収集対象外: 確認済み掲載媒体（システム判定）"
        company.updated_at = now
        db.add(
            Activity(
                company_id=company.id,
                activity_type="note",
                created_at=now,
                note=PREFIX + json.dumps(event, ensure_ascii=False),
            )
        )
        moved.append(str(company.id))
    return {"excluded_ids": moved, "protected_ids": protected, "checked": len(companies)}


def restore(db, company, actor_id, expected_updated_at):
    from fastapi import HTTPException

    event = latest_event(db, company.id)
    if (
        not event
        or event.get("action") != "EXCLUDE"
        or company.status != "excluded"
        or company.updated_at != expected_updated_at
        or event.get("after_updated_at") != company.updated_at.isoformat()
    ):
        raise HTTPException(
            409, "判定後に情報が変更されています。再読込して個別に確認してください。"
        )
    company.status = event["previous_status"]
    company.do_not_contact = event["previous_do_not_contact"]
    company.exclusion_reason = event["previous_exclusion_reason"]
    company.updated_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            company_id=company.id,
            activity_type="note",
            created_at=company.updated_at,
            note=PREFIX
            + json.dumps(
                {
                    "action": "RESTORE",
                    "origin": "HUMAN_OVERRIDE",
                    "actor_user_id": str(actor_id),
                    "website_url": company.website_url,
                    "after_updated_at": company.updated_at.isoformat(),
                    "restored_from": event,
                },
                ensure_ascii=False,
            ),
        )
    )
