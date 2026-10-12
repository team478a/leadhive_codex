"""Bounded period selection using captured event time, never Activity insertion time."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, and_, case, cast, func, or_
from sqlalchemy.dialects.postgresql import JSONB

# PostgreSQL 16 is the repository's supported DB. Guard both casts against corrupt history.
ISO_TZ = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)


def bounds(start, end):
    if start is None and end is None:
        return None
    if start is None or end is None or start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Positive timezone-bound period required")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def payload(note, prefix):
    text = func.substr(note, len(prefix) + 1)
    return case((func.pg_input_is_valid(text, "jsonb"), cast(text, JSONB)), else_=None)


def event_time(value, key):
    text = value[key].astext
    return case(
        (
            and_(text.op("~")(ISO_TZ), func.pg_input_is_valid(text, "timestamp with time zone")),
            cast(text, DateTime(timezone=True)),
        ),
        else_=None,
    )


def selection(time, period):
    # Unknown timestamps cannot be silently excluded from an allegedly complete period.
    return or_(time.is_(None), and_(time >= period[0], time < period[1]))


def contains(value, period):
    if period is None:
        return True
    if not isinstance(value, str):
        raise ValueError("Missing event time")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timezone required")
    return period[0] <= stamp < period[1]
