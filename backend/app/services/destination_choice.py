"""Read current Human preparation choice; invalid choices are never returned as active."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import DestinationChoiceEvent


def latest(db, company_id):
    return db.scalar(
        select(DestinationChoiceEvent)
        .where(DestinationChoiceEvent.company_id == company_id)
        .order_by(DestinationChoiceEvent.version.desc())
        .limit(1)
    )


def public_choice(db, company, rows, now=None):
    now = now or datetime.now(timezone.utc)
    row = latest(db, company.id)
    candidate = next((d for d in rows if row and d["id"] == row.destination_id), None)
    if row is None:
        state = "UNSELECTED"
    elif row.event_type == "REVOKED":
        state = "REVOKED"
    elif row.expires_at <= now:
        state = "EXPIRED"
    elif (
        candidate is None
        or candidate["expected_hash"] != row.snapshot_hash
        or candidate["review"]["version"] != row.purpose_review_version
    ):
        state = "STALE"
    elif candidate["status"] != "READY":
        state = "INELIGIBLE"
    else:
        state = "CURRENT"
    return dict(
        state=state,
        version=row.version if row else 0,
        actor_user_id=row.actor_user_id if row else None,
        created_at=row.created_at if row else None,
        expires_at=row.expires_at if row else None,
        recorded_destination=dict(
            id=row.destination_id, type=row.destination_type, destination=row.destination
        )
        if row
        else None,
        active_destination=dict(
            id=candidate["id"],
            type=candidate["type"],
            destination=candidate["destination"],
            payload_hash=row.snapshot_hash,
            purpose_review_version=row.purpose_review_version,
        )
        if state == "CURRENT" and candidate is not None and row is not None
        else None,
        execution_allowed=False,
    )
