"""Bounded, context-local Serper observations. No DB access in fetch threads."""

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from app.config import settings

MAX_RESPONSE_HITS = 100
MAX_TEXT = 4000


@dataclass
class DiscoveryCapture:
    rows: list[dict] = field(default_factory=list)
    received_count: int = 0
    omitted_count: int = 0
    response_received: bool = False


_buffer: ContextVar[DiscoveryCapture | None] = ContextVar("discovery_capture", default=None)


@contextmanager
def capturing_discovery():
    buffer = DiscoveryCapture()
    token = _buffer.set(buffer)
    try:
        yield buffer
    finally:
        _buffer.reset(token)


def capture_serper(items: list, *, page: int, requested: int) -> dict[int, UUID]:
    buffer = _buffer.get()
    if buffer is None:
        return {}
    buffer.response_received = True
    buffer.received_count += len(items)
    available = max(0, MAX_RESPONSE_HITS - len(buffer.rows))
    buffer.omitted_count += max(0, len(items) - available)
    ids = {}
    for position, item in enumerate(items[:available], start=1):
        item = item if isinstance(item, dict) else {}
        values: dict[str, str] = {}
        for key in ("title", "link", "snippet"):
            value = item.get(key)
            values[key] = value if isinstance(value, str) else ""
        # Never persist userinfo credentials returned by a malformed result URL.
        redacted = False
        try:
            parsed = urlsplit(values["link"])
            if parsed.username or parsed.password:
                values["link"] = urlunsplit(
                    parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1])
                )
                redacted = True
        except ValueError:
            pass
        raw_hash = hashlib.sha256(
            json.dumps(values, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        limit = settings.collection_discovery_field_chars
        truncated = any(len(value) > limit for value in values.values())
        snapshot: dict[str, object] = {key: value[:limit] for key, value in values.items()}
        snapshot.update(page=page, position=position, truncated=truncated, redacted=redacted)
        hit_id = uuid4()
        ids[position] = hit_id
        buffer.rows.append(
            dict(
                id=hit_id,
                position=position,
                snapshot=snapshot,
                raw_hash=raw_hash,
                disposition="RESPONSE_LIMIT" if position > requested else "CAPTURED",
            )
        )
    return ids
