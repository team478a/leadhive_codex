"""Observation stability is not entity truth; Pair features never decide identity."""

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from app.services.raw_benchmark import digest, ratio


def candidate_key(payload, snapshot_id):
    stable = payload.get("source_stable_id")
    if stable:
        return digest([payload.get("source"), stable])
    # Different redacted URLs must not collapse into a claimed identical observation.
    if payload.get("redacted_url_fields") and payload.get("source_payload_hash"):
        return digest([payload.get("source"), payload["source_payload_hash"]])
    values = [
        payload.get(k, "")
        for k in (
            "company_name",
            "address",
            "phone",
            "website",
            "email",
            "reference_url",
            "record_type",
        )
    ]
    if not any(values[:-1]):
        return str(snapshot_id)
    return digest([payload.get("source"), values])


def stability(sets):
    union = set().union(*sets) if sets else set()
    counts = Counter(k for keys in sets for k in keys)
    sufficient = len(sets) >= 2
    common = sum(n == len(sets) for n in counts.values()) if sufficient else None
    repeated = sum(n >= 2 for n in counts.values()) if sufficient else None
    single = sum(n == 1 for n in counts.values()) if sufficient else None
    return {
        "union": len(union),
        "intersection": common,
        "intersection_rate": ratio(common, len(union)) if sufficient else None,
        "repeat_discovery_rate": ratio(repeated, len(union)) if sufficient else None,
        "single_run_rate": ratio(single, len(union)) if sufficient else None,
        "run_count": len(sets),
    }


def normalized(v):
    return " ".join(unicodedata.normalize("NFKC", str(v or "")).split()).casefold()


def pair_features(left, right):
    def similarity(field):
        a, b = normalized(left.payload.get(field)), normalized(right.payload.get(field))
        return round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 6) if a and b else None

    def comparison(field):
        a, b = left.payload.get(field), right.payload.get(field)
        if field == "phone":
            a, b = re.sub(r"\D", "", str(a or "")), re.sub(r"\D", "", str(b or ""))
        else:
            try:
                a, b = urlsplit(str(a or "")).hostname, urlsplit(str(b or "")).hostname
            except ValueError:
                return None
        return a == b if a and b else None

    return {
        "feature_version": "raw-pair-v1",
        "name_similarity": similarity("company_name"),
        "address_similarity": similarity("address"),
        "phone_equal": comparison("phone"),
        "domain_equal": comparison("website"),
        "sources": [left.payload.get("source"), right.payload.get("source")],
        "queries": [left.payload.get("source_query"), right.payload.get("source_query")],
        "snapshot_hashes": [left.snapshot_hash, right.snapshot_hash],
        "automatic_identity": False,
    }
