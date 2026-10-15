"""Server-generated collection provenance; never inspect credentials or request content."""

import hashlib
import json
import os
import re
import socket
import sys
import uuid
from types import CodeType
from typing import Any

PROCESS_ID = str(uuid.uuid4())


def code_value(value: Any) -> Any:
    """Canonicalize loaded bytecode without marshal's object-reference state."""
    if isinstance(value, CodeType):
        return {
            "code": value.co_code.hex(),
            "constants": [code_value(item) for item in value.co_consts],
            "names": value.co_names,
            "variables": value.co_varnames,
            "freevars": value.co_freevars,
            "cellvars": value.co_cellvars,
            "args": (value.co_argcount, value.co_posonlyargcount, value.co_kwonlyargcount),
            "flags": value.co_flags,
            "exceptions": value.co_exceptiontable.hex(),
        }
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, tuple):
        return [code_value(item) for item in value]
    if isinstance(value, frozenset):
        return {"frozenset": sorted(json.dumps(code_value(item), sort_keys=True) for item in value)}
    if isinstance(value, complex):
        return {"complex": (value.real, value.imag)}
    if value is Ellipsis:
        return {"ellipsis": True}
    return value


def code_fingerprint(function) -> str | None:
    code = getattr(function, "__code__", None)
    return (
        hashlib.sha256(json.dumps(code_value(code), sort_keys=True).encode()).hexdigest()
        if isinstance(code, CodeType)
        else None
    )


def runtime_snapshot() -> dict:
    # Fingerprint loaded code, rather than files which could differ from a running
    # interpreter. These are diagnostic hashes, not authorization proofs.
    from app.services import collection_discovery as raw
    from app.services import collection_jobs as ingestion
    from app.services import collection_scheduler as fair
    from app.services import target_collection as quota

    functions = {
        "raw.classify_hit": raw.classify_hit,
        "raw.canonicalize_url": raw.canonicalize_url,
        "raw.presence_classifier": raw.classify,
        "raw.aggregator_classifier": raw.is_aggregator_domain,
        "raw.persist_discovery": raw.persist_discovery,
        "ingestion.classify_candidate": ingestion.classify_candidate,
        "ingestion.save_candidates": ingestion.save_candidates,
        "quota.classify_candidate": quota.classify_candidate,
        "quota.bounded_candidates": quota.bounded_candidates,
        "target.run": quota.run,
        "fair.run": fair.run,
    }
    fingerprints = {name: code_fingerprint(function) for name, function in functions.items()}
    rule_names = (
        "SOCIAL",
        "JOBS",
        "THIRD_PARTY_DOMAINS",
        "JOB_SOURCE_DOMAINS",
        "ARTICLE_PATH_SEGMENTS",
        "COMPARISON_TITLE_MARKERS",
        "NUMBERED_SELECTION_MARKERS",
    )
    rules: dict[str, Any] = {name: sorted(getattr(raw, name, ())) for name in rule_names}
    rules["AGGREGATOR_DOMAINS"] = sorted(
        raw.is_aggregator_domain.__globals__.get("AGGREGATOR_DOMAINS", ())
    )
    rules["PRESENCE_DOMAINS"] = sorted(raw.DOMAINS.items())
    fingerprints["classification.rules"] = hashlib.sha256(
        json.dumps(rules, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    return {
        "schema_version": 1,
        "commit": commit.lower() if re.fullmatch(r"[a-fA-F0-9]{40}", commit) else None,
        "process_id": PROCESS_ID,
        "pid": os.getpid(),
        "instance_id": hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16],
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "fingerprint_format": "sha256-python-code-v1",
        "fingerprints": fingerprints,
    }


def annotate_claim(job) -> None:
    """Called under the existing claim lock, before its commit and any search."""
    record = {
        "attempt": job.attempt_count,
        "claim_id": str(job.worker_id),
        "claimed_at": job.started_at.isoformat(),
        "runtime": runtime_snapshot(),
    }
    history = job.payload.get("collection_runtime_history") or []
    job.payload = {
        **job.payload,
        "collection_runtime": record,
        "collection_runtime_history": [*history, record],
    }
