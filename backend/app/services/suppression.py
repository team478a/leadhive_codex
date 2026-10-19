from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import OrganizationAuditEvent, SuppressionEntry

NON_RELEASABLE_SOURCES = {
    "email_unsubscribe",
    "reply_unsubscribe",
    "complaint",
    "bounce",
    "global_opt_out",
}


def active_suppression_scope_condition(project_id, organization_id):
    return and_(
        SuppressionEntry.released_at.is_(None),
        or_(
            and_(
                SuppressionEntry.scope == "project",
                SuppressionEntry.project_id == project_id,
            ),
            and_(
                SuppressionEntry.scope == "organization",
                SuppressionEntry.organization_id == organization_id,
            ),
            SuppressionEntry.scope == "global",
        ),
    )


def add_suppression(
    db: Session,
    *,
    scope: str,
    reason: str,
    source: str,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
    domain: str = "",
    email: str = "",
    phone: str = "",
    actor_user_id: UUID | None = None,
) -> SuppressionEntry:
    normalized_domain = (domain or "").strip().rstrip(".").lower()
    if normalized_domain.startswith("www."):
        normalized_domain = normalized_domain[4:]
    normalized_email = (email or "").strip().lower()
    normalized_phone = (phone or "").strip()
    existing = db.scalar(
        select(SuppressionEntry).where(
            SuppressionEntry.scope == scope,
            SuppressionEntry.organization_id == organization_id,
            SuppressionEntry.project_id == project_id,
            SuppressionEntry.released_at.is_(None),
            SuppressionEntry.domain == normalized_domain,
            SuppressionEntry.email == normalized_email,
            SuppressionEntry.phone == normalized_phone,
        )
    )
    if existing is not None:
        return existing
    entry_id = uuid4()
    entry = SuppressionEntry(
        id=entry_id,
        scope=scope,
        source=source,
        project_id=project_id,
        organization_id=organization_id,
        created_by_user_id=actor_user_id,
        domain=normalized_domain,
        email=normalized_email,
        phone=normalized_phone,
        reason=reason,
    )
    db.add(entry)
    if scope in {"organization", "global"}:
        db.add(
            OrganizationAuditEvent(
                organization_id=organization_id,
                suppression_entry_id=entry_id,
                actor_user_id=actor_user_id,
                event_type="suppression_created",
                reason=reason,
                details={"scope": scope, "source": source},
            )
        )
    return entry


def release_suppression(
    db: Session,
    entry: SuppressionEntry,
    *,
    actor_user_id: UUID,
    reason: str,
    allow_global_operator_release: bool = False,
) -> None:
    global_operator_release = allow_global_operator_release and entry.scope == "global"
    if entry.source in NON_RELEASABLE_SOURCES and not global_operator_release:
        raise ValueError("This suppression source cannot be released.")
    if entry.released_at is not None:
        raise ValueError("This suppression entry has already been released.")
    entry.released_at = datetime.now(timezone.utc)
    entry.released_by_user_id = actor_user_id
    entry.release_reason = reason
    db.add(
        OrganizationAuditEvent(
            organization_id=entry.organization_id,
            suppression_entry_id=entry.id,
            actor_user_id=actor_user_id,
            event_type="suppression_released",
            reason=reason,
            details={"scope": entry.scope, "source": entry.source},
        )
    )
