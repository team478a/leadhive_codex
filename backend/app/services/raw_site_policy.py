"""Official-site candidate policy; never creates or changes Human truth labels."""

from collections.abc import Mapping
from urllib.parse import urlsplit

from app.services.scraper import is_aggregator_domain

RULE_VERSION = "official-site-only-v1"


def site_policy(payload: Mapping[str, object]) -> dict[str, str]:
    # A third-party reference does not disqualify a separate own-site candidate.
    value = payload.get("website") or payload.get("reference_url")
    try:
        parsed = urlsplit(value if isinstance(value, str) else "")
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme in {"http", "https"} and host and is_aggregator_domain(host):
            return {
                "status": "EXCLUDED_THIRD_PARTY",
                "reason_code": "PORTAL_OR_AGGREGATOR",
                "rule_version": RULE_VERSION,
            }
    except ValueError:
        pass
    # Absence from the blocklist is not evidence that a site is official.
    return {
        "status": "REVIEW_REQUIRED",
        "reason_code": "OFFICIAL_SITE_UNCONFIRMED",
        "rule_version": RULE_VERSION,
    }
