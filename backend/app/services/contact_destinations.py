"""Project-local destination inventory. It is not a permission or send authority."""

import hashlib
import ipaddress
from urllib.parse import urlsplit

from sqlalchemy import delete, select

from app.models import Company, ContactDestination, FormProfile, LeadDestinationLink
from app.services.collection import canonicalize_url


def normalize_destination(channel: str, value: str) -> str:
    value = value.strip()
    if channel == "email":
        if len(value) > 320 or value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("Invalid destination")
        return value.casefold()
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError("Invalid destination")
    canonical, _ = canonicalize_url(value)
    host = parsed.hostname or ""
    if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local")):
        raise ValueError("Invalid destination")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Invalid destination")
    return canonical


def candidates(db, company):
    values = [
        ("email", company.email, company.contact_source_url),
        ("form", company.contact_url, company.contact_source_url),
    ]
    for profile in db.scalars(
        select(FormProfile).where(
            FormProfile.company_id == company.id, FormProfile.form_found.is_(True)
        )
    ):
        values.append(("form", profile.form_url, profile.form_url))
    result = {}
    for channel, value, source in values:
        if not value:
            continue
        try:
            normalized = normalize_destination(channel, value)
        except ValueError:
            continue
        result[(channel, normalized)] = source or ""
    return result


def sync_company(db, company):
    links = []
    for (channel, value), source in candidates(db, company).items():
        key = hashlib.sha256(value.encode()).hexdigest()
        destination = db.scalar(
            select(ContactDestination).where(
                ContactDestination.project_id == company.project_id,
                ContactDestination.destination_type == channel,
                ContactDestination.shared_destination_key == key,
            )
        )
        if destination is None:
            destination = ContactDestination(
                project_id=company.project_id,
                destination_type=channel,
                destination=value,
                shared_destination_key=key,
            )
            db.add(destination)
            db.flush()
        link = db.scalar(
            select(LeadDestinationLink).where(
                LeadDestinationLink.company_id == company.id,
                LeadDestinationLink.destination_id == destination.id,
            )
        )
        if link is None:
            link = LeadDestinationLink(company_id=company.id, destination_id=destination.id)
            db.add(link)
        link.source_url = source
        links.append(destination.id)
    db.execute(
        delete(LeadDestinationLink).where(
            LeadDestinationLink.company_id == company.id,
            LeadDestinationLink.destination_id.not_in(links),
        )
    )
    db.flush()


def linked_inventory(db, company):
    rows = db.scalars(
        select(ContactDestination)
        .join(LeadDestinationLink, LeadDestinationLink.destination_id == ContactDestination.id)
        .where(
            LeadDestinationLink.company_id == company.id,
            ContactDestination.project_id == company.project_id,
            ContactDestination.active.is_(True),
        )
    ).all()
    result = []
    current = candidates(db, company)
    for row in rows:
        linked = db.scalars(
            select(LeadDestinationLink.company_id)
            .join(Company, Company.id == LeadDestinationLink.company_id)
            .where(
                LeadDestinationLink.destination_id == row.id,
                Company.project_id == company.project_id,
            )
        ).all()
        result.append(
            {
                "id": row.id,
                "type": row.destination_type,
                "destination": row.destination,
                "scope": "group" if len(linked) > 1 else row.scope,
                "purpose": row.purpose,
                "linked_lead_count": len(linked),
                "shared": len(linked) > 1,
                "current": (row.destination_type, row.destination) in current,
                "verified": False,
                "permission_status": "UNCERTAIN",
                "execution_allowed": False,
            }
        )
    return result
