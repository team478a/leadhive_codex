"""Exact-host source memory; no automatic domain-wide inference from an article."""

from sqlalchemy import select

from app.models import SourceDomainExclusion
from app.services.collection import canonicalize_url


def domain_key(url):
    return canonicalize_url(url)[1].lower().rstrip(".").removeprefix("www.")


def domains(db, project_id):
    return set(
        db.scalars(
            select(SourceDomainExclusion.domain).where(
                SourceDomainExclusion.project_id == project_id,
                SourceDomainExclusion.active.is_(True),
            )
        )
    )


def excluded(db, project_id, url):
    return bool(url) and domain_key(url) in domains(db, project_id)
