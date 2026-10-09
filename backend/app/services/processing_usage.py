"""Count HTTP attempts in bounded collection contexts, never budget reservations.

Context-local buffers are safe for worker threads; only the owning caller writes
its SQLAlchemy session. An interrupted process can lose a buffer, so reports
always identify partial coverage and never infer a complete processing cost.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from time import monotonic

from app.models import LeadProcessingUsage

_buffer: ContextVar[list | None] = ContextVar("lead_processing_usage", default=None)


@contextmanager
def capture_usage():
    rows: list[dict] = []
    token = _buffer.set(rows)
    try:
        yield rows
    finally:
        _buffer.reset(token)


def measured_request(provider, request, *args, **kwargs):
    rows = _buffer.get()
    if rows is None:
        return request(*args, **kwargs)
    start, clock = datetime.now(timezone.utc), monotonic()
    status = "failed"
    try:
        response = request(*args, **kwargs)
        if 200 <= response.status_code < 300:
            status = "completed"
        return response
    finally:
        rows.append(
            dict(
                kind="search",
                provider=provider,
                status=status,
                started_at=start,
                elapsed_ms=max(0, int((monotonic() - clock) * 1000)),
            )
        )


def persist_usage(db, rows, project_id, *, collection_job_id=None, company_id=None):
    for values in rows:
        db.add(
            LeadProcessingUsage(
                project_id=project_id,
                collection_job_id=collection_job_id,
                company_id=company_id,
                **values,
            )
        )
    db.commit()


def measured_search(db, collection, search, keyword, region, limit):
    from app.services.collection_discovery import persist_discovery
    from app.services.discovery_capture import capturing_discovery

    with capture_usage() as rows, capturing_discovery() as discovery:
        try:
            return search(keyword, region, limit)
        finally:
            persist_discovery(db, collection, discovery)
            persist_usage(db, rows, collection.project_id, collection_job_id=collection.id)


@contextmanager
def ai_operation(db, company, *, model, provider="openai"):
    """SDK operation, not a physical-request count (the SDK may retry)."""
    start, clock = datetime.now(timezone.utc), monotonic()
    values = dict(kind="ai", provider=provider, model=model, status="failed", started_at=start)
    try:
        yield values
    finally:
        values["elapsed_ms"] = max(0, int((monotonic() - clock) * 1000))
        persist_usage(db, [values], company.project_id, company_id=company.id)
