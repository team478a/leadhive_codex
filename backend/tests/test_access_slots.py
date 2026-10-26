import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.database import engine
from app.services import access_slots


def unique_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}.example"


def test_shared_slot_serializes_same_host_across_connections():
    host = unique_key("same")
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        waits = list(executor.map(lambda _: access_slots.reserve_access_slot(host), range(2)))
    elapsed = time.monotonic() - started

    assert min(waits) < 0.2
    assert max(waits) >= 0.8
    assert elapsed >= 0.8


def test_shared_slot_does_not_serialize_different_hosts():
    hosts = [unique_key("left"), unique_key("right")]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        waits = list(executor.map(access_slots.reserve_access_slot, hosts))

    assert max(waits) < 0.2
    assert time.monotonic() - started < 2


def test_shared_slot_defers_when_wait_exceeds_limit():
    host = unique_key("deferred")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO host_access_slots (host, next_allowed_at, updated_at) "
                "VALUES (:host, :next_allowed_at, now())"
            ),
            {
                "host": host,
                "next_allowed_at": datetime.now(timezone.utc) + timedelta(seconds=31),
            },
        )

    with pytest.raises(access_slots.AccessSlotDeferred) as error:
        access_slots.reserve_access_slot(host, max_wait_seconds=0.1)

    assert error.value.wait_seconds > 30
    with engine.connect() as connection:
        remaining = connection.execute(
            text(
                "SELECT extract(epoch FROM (next_allowed_at - clock_timestamp())) "
                "FROM host_access_slots WHERE host = :host"
            ),
            {"host": host},
        ).scalar_one()
    assert 25 < float(remaining) < 32


def test_shared_slot_uses_local_fallback_when_database_is_unavailable(monkeypatch):
    class BrokenEngine:
        def begin(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(access_slots, "engine", BrokenEngine())
    access_slots.reserve_access_slot(unique_key("fallback"), interval_seconds=0)


def test_api_slot_applies_combined_rate_across_connections():
    provider = f"serper-{uuid.uuid4().hex}"
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        waits = list(
            executor.map(lambda _: access_slots.wait_for_api_access(provider, 2), range(2))
        )

    assert max(waits) >= 0.35
    assert time.monotonic() - started >= 0.35
