"""Version-bound Human purpose evidence. No permission overrides or outbound I/O."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import (
    ContactPerson,
    DestinationReviewEvent,
    FormProfile,
    FormProfileField,
    LeadDestinationLink,
    LeadSiteEvidence,
)
from app.services.lead_identity import identity_hash

CANONICAL_VERSION = "destination-review-v1"


def snapshot_hash(db, company, destination):
    profiles = db.scalars(
        select(FormProfile).where(FormProfile.company_id == company.id).order_by(FormProfile.id)
    ).all()
    fields = db.scalars(
        select(FormProfileField)
        .where(FormProfileField.form_profile_id.in_([p.id for p in profiles]))
        .order_by(FormProfileField.id)
    ).all()
    contacts = db.scalars(
        select(ContactPerson)
        .where(ContactPerson.company_id == company.id)
        .order_by(ContactPerson.id)
    ).all()
    links = db.scalars(
        select(LeadDestinationLink)
        .where(
            LeadDestinationLink.company_id == company.id,
            LeadDestinationLink.destination_id == destination.id,
        )
        .order_by(LeadDestinationLink.id)
    ).all()
    sites = db.scalars(
        select(LeadSiteEvidence)
        .where(LeadSiteEvidence.company_id == company.id)
        .order_by(LeadSiteEvidence.id)
    ).all()
    values = dict(
        schema=CANONICAL_VERSION,
        project=str(company.project_id),
        company=str(company.id),
        identity=identity_hash(company),
        email=company.email,
        contact_url=company.contact_url,
        contact_quality=company.contact_quality_status,
        do_not_contact=company.do_not_contact,
        protected=sorted(company.protected_fields or []),
        destination=[
            str(destination.id),
            destination.destination_type,
            destination.destination,
            destination.active,
            destination.purpose,
            destination.scope,
        ],
        links=[[str(link.id), link.source_url] for link in links],
        sites=[[str(s.id), s.identity_hash, s.confidence, str(s.observed_at)] for s in sites],
        contacts=[
            [str(c.id), c.email, c.verification_status, c.source_url, str(c.updated_at)]
            for c in contacts
        ],
        profiles=[
            [
                str(p.id),
                p.form_url,
                p.action_url,
                p.fingerprint,
                p.form_status,
                p.sales_contact_status,
                p.captcha_type,
                p.is_primary,
                p.delivery_supported,
                p.form_found,
                p.confirmation_page,
                p.analysis_version,
                str(p.last_analyzed_at),
                str(p.updated_at),
            ]
            for p in profiles
        ],
        fields=[
            [
                str(f.id),
                f.name,
                f.selector,
                f.field_type,
                f.required,
                f.mapped_key,
                f.confidence,
                f.decision_source,
                f.options,
                f.recommended_value,
                f.label,
                str(f.updated_at),
            ]
            for f in fields
        ],
    )
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def latest(db, company_id, destination_id):
    return db.scalar(
        select(DestinationReviewEvent)
        .where(
            DestinationReviewEvent.company_id == company_id,
            DestinationReviewEvent.destination_id == destination_id,
        )
        .order_by(DestinationReviewEvent.version.desc())
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
    if row.snapshot_hash != digest or row.canonicalization_version != CANONICAL_VERSION:
        return "STALE"
    return "CURRENT"


def public_review(row, digest, now=None):
    return dict(
        state=state(row, digest, now),
        version=row.version if row else 0,
        reviewed_by_user_id=row.actor_user_id if row else None,
        created_at=row.created_at if row else None,
        expires_at=row.expires_at if row else None,
        purpose=row.purpose if row else "unknown",
        scope=row.scope if row else "unknown",
        source_url=row.source_url if row else "",
        evidence_excerpt=row.evidence_excerpt if row else "",
    )
