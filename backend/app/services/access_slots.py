import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger("leadhive")
MAX_ACCESS_SLOT_WAIT_SECONDS = 30.0
_LOCAL_LAST_ACCESS: dict[str, float] = {}
_LOCAL_LOCK = threading.Lock()
_LAST_CLEANUP = 0.0
_CLEANUP_LOCK = threading.Lock()


class AccessSlotDeferred(Exception):
    def __init__(self, resource: str, wait_seconds: float):
        super().__init__(f"Access slot for {resource} is deferred by {wait_seconds:.3f}s")
        self.resource = resource
        self.wait_seconds = wait_seconds


def normalize_access_key(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("api:"):
        return normalized[:255]
    return normalized.removeprefix("www.").rstrip(".")[:255]


def _local_wait(resource: str, interval_seconds: float, max_wait_seconds: float) -> None:
    with _LOCAL_LOCK:
        now = time.monotonic()
        if len(_LOCAL_LAST_ACCESS) > 1000:
            stale = [key for key, value in _LOCAL_LAST_ACCESS.items() if now - value > 86400]
            for key in stale:
                _LOCAL_LAST_ACCESS.pop(key, None)
        wait_seconds = max(0.0, interval_seconds - (now - _LOCAL_LAST_ACCESS.get(resource, 0.0)))
        if wait_seconds > max_wait_seconds:
            raise AccessSlotDeferred(resource, wait_seconds)
        if wait_seconds:
            time.sleep(wait_seconds)
        _LOCAL_LAST_ACCESS[resource] = time.monotonic()


def reserve_access_slot(
    resource: str,
    *,
    interval_seconds: float = 1.0,
    max_wait_seconds: float = MAX_ACCESS_SLOT_WAIT_SECONDS,
) -> float:
    key = normalize_access_key(resource)
    if not key:
        return 0.0
    try:
        with engine.begin() as connection:
            wait_seconds = connection.execute(
                text(
                    """
                    INSERT INTO host_access_slots (host, next_allowed_at, updated_at)
                    VALUES (
                      :host,
                      clock_timestamp() + make_interval(secs => :interval_seconds),
                      clock_timestamp()
                    )
                    ON CONFLICT (host) DO UPDATE
                      SET next_allowed_at = CASE
                            WHEN host_access_slots.next_allowed_at <= clock_timestamp()
                              THEN clock_timestamp()
                                   + make_interval(secs => :interval_seconds)
                            ELSE greatest(
                                   host_access_slots.next_allowed_at,
                                   clock_timestamp()
                                   + make_interval(secs => :interval_seconds)
                                 )
                                 + make_interval(secs => :interval_seconds)
                          END,
                          updated_at = clock_timestamp()
                    RETURNING greatest(
                      0,
                      extract(epoch FROM (
                        next_allowed_at
                        - make_interval(secs => :interval_seconds)
                        - clock_timestamp()
                      ))
                    )
                    """
                ),
                {"host": key, "interval_seconds": interval_seconds},
            ).scalar_one()
            wait = float(wait_seconds or 0.0)
            if wait > max_wait_seconds:
                raise AccessSlotDeferred(key, wait)
        if wait:
            time.sleep(wait)
        return wait
    except AccessSlotDeferred:
        raise
    except Exception as exc:
        logger.warning(
            "shared access slot unavailable; using local fallback: %s", type(exc).__name__
        )
        _local_wait(key, interval_seconds, max_wait_seconds)
        return 0.0


def wait_for_host_access(host: str) -> float:
    return reserve_access_slot(host, interval_seconds=1.0)


def wait_for_api_access(provider: str, requests_per_second: float) -> float:
    return reserve_access_slot(f"api:{provider}", interval_seconds=1.0 / requests_per_second)


def cleanup_old_access_slots() -> int:
    global _LAST_CLEANUP
    now = time.monotonic()
    with _CLEANUP_LOCK:
        if now - _LAST_CLEANUP < timedelta(hours=1).total_seconds():
            return 0
        try:
            with engine.begin() as connection:
                result = connection.execute(
                    text(
                        "DELETE FROM host_access_slots "
                        "WHERE next_allowed_at < now() - interval '1 day'"
                    )
                )
            _LAST_CLEANUP = now
            return result.rowcount or 0
        except Exception as exc:
            logger.warning("access slot cleanup failed: %s", type(exc).__name__)
            return 0
