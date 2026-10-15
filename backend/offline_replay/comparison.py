"""Audited Serper boundary projections, not a legacy application runner.

Legacy policy data is read as Python literals, never imported or executed.
Current URL/domain functions are isolated from their application imports.
No fixture URL is opened and no Company or Human truth is created.
"""

import ast
import copy
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import FunctionType
from typing import Any
from urllib.parse import parse_qsl, urlparse, urlsplit, urlunsplit

from offline_replay.source_policy import SourcePolicy

LEGACY_COMMIT = "393f690e34c7a5fbdddd4b15e0285aa2ff313269"
CURRENT_COMMIT = "31ec306819a5485de3c3cc9f3bb11a3da3cc6d0f"
VERSION = "serper-boundary-replay-v1"
MAX_HITS = 1000


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def literal(source: str, name: str) -> list[str]:
    """Extract allowlisted policy data without running external Python."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, (list, set, tuple)) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(f"Invalid literal policy: {name}")
            return sorted(set(value))
    raise ValueError(f"Missing policy: {name}")


def isolated_function(source: str, name: str, namespace: dict[str, Any]) -> FunctionType:
    """Load only the reviewed pure current function, with no imports or I/O builtins."""
    matches = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Missing current function: {name}")
    function = matches[0]
    allowed_calls = {"urlsplit", "urlunsplit", "len", "any", "ValueError"}
    allowed_methods = {
        "strip",
        "lower",
        "rstrip",
        "encode",
        "decode",
        "startswith",
        "endswith",
        "removeprefix",
        "split",
    }
    for node in ast.walk(function):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise ValueError("Current projection is no longer pure")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Private attribute is forbidden")
        if isinstance(node, ast.Call):
            target = node.func
            if not (
                isinstance(target, ast.Name)
                and target.id in allowed_calls
                or isinstance(target, ast.Attribute)
                and target.attr in allowed_methods
            ):
                raise ValueError("Unreviewed call in current projection")
    # Types/decorators/defaults are not needed to run these two pure functions.
    if function.decorator_list or function.args.defaults or function.args.kw_defaults:
        raise ValueError("Unexpected function decoration/defaults")
    function.returns = None
    for argument in function.args.args:
        argument.annotation = None
    tree = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    environment = {
        "__builtins__": {
            "len": len,
            "any": any,
            "ValueError": ValueError,
            "UnicodeError": UnicodeError,
        },
        "urlsplit": urlsplit,
        "urlunsplit": urlunsplit,
        **namespace,
    }
    exec(compile(tree, "<reviewed-current-projection>", "exec"), environment)  # noqa: S102
    return environment[name]


class Policies:
    def __init__(
        self,
        legacy_source: str,
        current_collection: str,
        current_scraper: str,
        *,
        source_commits: dict[str, str] | None = None,
    ):
        self.source_commits = dict(source_commits or {})
        self.legacy_domains = literal(legacy_source, "KNOWN_AGGREGATOR_DOMAINS")
        self.public_suffixes = literal(legacy_source, "PUBLIC_ORG_DOMAIN_SUFFIXES")
        self.public_patterns = literal(legacy_source, "PUBLIC_ORG_TITLE_PATTERNS")
        self.canonicalize = isolated_function(current_collection, "canonicalize_url", {})
        domains = set(literal(current_scraper, "AGGREGATOR_DOMAINS"))
        self.is_aggregator = isolated_function(
            current_scraper, "is_aggregator_domain", {"AGGREGATOR_DOMAINS": domains}
        )
        self.source_hashes = {
            "legacy_aggregator": hashlib.sha256(legacy_source.encode()).hexdigest(),
            "current_collection": hashlib.sha256(current_collection.encode()).hexdigest(),
            "current_scraper": hashlib.sha256(current_scraper.encode()).hexdigest(),
        }

    def legacy(self, hit: dict[str, Any], seen: set[str]) -> dict[str, Any]:
        """Model /urls-preview only; do not apply the other legacy collection routes."""
        url = hit["link"]
        if not url:
            return decision("SKIPPED", "EMPTY_URL")
        try:
            parsed = urlparse(url)
        except ValueError:
            return decision("ERROR", "LEGACY_URL_PARSE_ERROR")
        domain = parsed.netloc.lower().strip().removeprefix("www.")
        if domain in seen:
            return decision("DUPLICATE", "LEGACY_DOMAIN_DUPLICATE", domain=domain)
        seen.add(domain)
        excluded = any(value in domain for value in self.legacy_domains)
        public = any(
            domain == suffix or domain.endswith("." + suffix) for suffix in self.public_suffixes
        ) or any(re.search(pattern, hit["title"]) for pattern in self.public_patterns)
        return decision(
            "EXCLUDED" if excluded or public else "CANDIDATE",
            "LEGACY_REFERENCE_OR_PUBLIC" if excluded or public else "LEGACY_PREVIEW_CANDIDATE",
            website_url=f"{parsed.scheme}://{parsed.netloc}/",
            domain=domain,
        )

    def current(self, hit: dict[str, Any], seen: set[str]) -> dict[str, Any]:
        try:
            canonical, domain = self.canonicalize(hit["link"])
        except (ValueError, UnicodeError):
            return decision("SKIPPED", "INVALID_URL")
        if self.is_aggregator(domain):
            return decision("EXCLUDED", "KNOWN_AGGREGATOR", domain=domain)
        if domain in seen:
            return decision("DUPLICATE", "CURRENT_COMPANY_DOMAIN_DUPLICATE", domain=domain)
        seen.add(domain)
        return decision(
            "CANDIDATE", "CURRENT_INGESTION_CANDIDATE", website_url=canonical, domain=domain
        )


def decision(state: str, reason: str, **fields: Any) -> dict[str, Any]:
    return {"state": state, "reason": reason, **fields}


def validate_fixture(fixture: dict[str, Any]) -> None:
    reject_secrets(fixture)
    if fixture.get("schema_version") != "serper-replay-input-v1":
        raise ValueError("Unsupported fixture schema")
    if fixture.get("dataset_kind") not in {"SYNTHETIC", "PRIVATE_LICENSED_RAW"}:
        raise ValueError("Dataset kind must be explicit")
    runs = fixture.get("runs")
    if not isinstance(runs, list) or len(runs) > 12:
        raise ValueError("At most 12 runs are supported")
    ids = set()
    repeated: Counter = Counter()
    total = 0
    for run in runs:
        if not isinstance(run, dict) or run.get("source") != "serper":
            raise ValueError("This projection supports Serper only")
        for field in ("run_id", "query_id", "query", "region", "industry", "observed_at"):
            if not isinstance(run.get(field), str) or not run[field].strip():
                raise ValueError(f"Missing provenance: {field}")
        if datetime.fromisoformat(run["observed_at"]).tzinfo is None:
            raise ValueError("Observation timestamp must include a timezone")
        if run["run_id"] in ids:
            raise ValueError("Duplicate run ID")
        ids.add(run["run_id"])
        key = (run["source"], run["query"], run["region"])
        repeated[key] += 1
        if repeated[key] > 3:
            raise ValueError("At most three repeat runs per query are supported")
        if run.get("status") not in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("Unknown run status")
        if not isinstance(run.get("organic"), list):
            raise ValueError("organic must be a list")
        total += len(run["organic"])
        for hit in run["organic"]:
            if not isinstance(hit, dict) or not all(
                isinstance(hit.get(field, ""), str) for field in ("title", "link", "snippet")
            ):
                raise ValueError("Invalid raw hit")
    if total > MAX_HITS:
        raise ValueError("Offline fixture hit ceiling exceeded")


def reject_secrets(value: Any) -> None:
    """Reject explicit credential fields/URLs rather than modifying immutable raw input."""
    forbidden = {
        "password",
        "api_key",
        "apikey",
        "secret",
        "authorization",
        "cookie",
        "access_token",
        "refresh_token",
        "smtp_password",
        "imap_password",
    }
    if isinstance(value, dict):
        if any(str(key).lower() in forbidden for key in value):
            raise ValueError("Credential fields are forbidden in benchmark fixtures")
        for nested in value.values():
            reject_secrets(nested)
    elif isinstance(value, list):
        for nested in value:
            reject_secrets(nested)
    elif isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(value)
        except ValueError:
            return  # Invalid URL remains a measured adapter error, not a success.
        if (
            parsed.username
            or parsed.password
            or any(
                name.lower() in forbidden | {"token", "key"} for name, _ in parse_qsl(parsed.query)
            )
        ):
            raise ValueError("Credential URLs are forbidden in benchmark fixtures")


def compare(
    fixture: dict[str, Any], policies: Policies, *, source_policy: SourcePolicy | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_fixture(fixture)
    input_hash = digest(fixture)
    private = {
        "schema_version": VERSION,
        "input_hash": input_hash,
        "dataset_kind": fixture["dataset_kind"],
        "source_hashes": policies.source_hashes,
        "source_commits": policies.source_commits,
        "runs": [],
    }
    for run in fixture["runs"]:
        # Independent empty-project projection per run: repeat discovery is not an error.
        seen: dict[str, set[str]] = {"legacy_preview": set(), "current_ingestion": set()}
        observations = []
        eligible_seen: set[str] = set()
        for position, original in enumerate(run["organic"], 1):
            hit = {field: original.get(field, "") for field in ("title", "link", "snippet")}
            observations.append(
                {
                    "position": position,
                    "raw": copy.deepcopy(original),
                    "raw_hash": digest(original),
                    "legacy_preview": policies.legacy(hit, seen["legacy_preview"]),
                    "current_ingestion": policies.current(hit, seen["current_ingestion"]),
                    "human_truth": None,
                }
            )
            if source_policy is not None:
                eligible, kind, reason = source_policy.eligible(
                    {**hit, "redacted": original.get("redacted", False)}
                )
                observations[-1]["current_ingestion_eligibility"] = (
                    {
                        **policies.current(hit, eligible_seen),
                        "classification": kind,
                        "classification_reason": reason,
                    }
                    if eligible
                    else decision(
                        "EXCLUDED",
                        "NON_COMPANY_SOURCE",
                        classification=kind,
                        classification_reason=reason,
                    )
                )
        private["runs"].append(
            {
                "provenance": {k: v for k, v in run.items() if k != "organic"},
                "observations": observations,
            }
        )
    if digest(fixture) != input_hash:
        raise RuntimeError("Raw fixture was mutated")
    summary: dict[str, Any] = {
        "schema_version": VERSION,
        "dataset_kind": fixture["dataset_kind"],
        "evaluation": "SYNTHETIC_BEHAVIOR_ONLY"
        if fixture["dataset_kind"] == "SYNTHETIC"
        else "UNREVIEWED_PRIVATE_REPLAY",
        "legacy_commit": policies.source_commits.get("legacy"),
        "current_commit": policies.source_commits.get("current"),
        "stage": "RAW_COLLECTION_BOUNDARY_REPLAY",
        "input_hash": input_hash,
        "source_hashes": policies.source_hashes,
        "runs": [],
        "human_reviewed": 0,
        "strict_precision": None,
        "resolved_precision": None,
        "official_site_accuracy": None,
        "contact_discovery_rate": None,
        "api_cost": None,
        "coverage": None,
        "limitations": [
            "Boundary projections only; no whole-app legacy execution or DB ingestion.",
            "No Human labels or official-site/contact validation are inferred.",
            "Empty independent project per run; no suppression or existing DB state.",
        ],
        "safety": dict(
            external_requests=0,
            ai_calls=0,
            completion_jobs=0,
            approvals=0,
            email_sent=0,
            form_posts=0,
        ),
    }
    for run in private["runs"]:
        rows = run["observations"]
        summary["runs"].append(
            {
                "ordinal": len(summary["runs"]) + 1,
                "status": run["provenance"]["status"],
                "raw_hits": len(rows),
                "decision_differences": sum(
                    row["legacy_preview"]["state"] != row["current_ingestion"]["state"]
                    for row in rows
                ),
                "candidate_url_differences": sum(
                    row["legacy_preview"].get("website_url")
                    != row["current_ingestion"].get("website_url")
                    for row in rows
                    if row["legacy_preview"]["state"] == "CANDIDATE"
                    and row["current_ingestion"]["state"] == "CANDIDATE"
                ),
                "projections": {
                    name: dict(Counter(row[name]["state"] for row in rows))
                    for name in ("legacy_preview", "current_ingestion")
                },
            }
        )
        if source_policy is not None:
            summary["runs"][-1]["projections"]["current_ingestion_eligibility"] = dict(
                Counter(row["current_ingestion_eligibility"]["state"] for row in rows)
            )
    if source_policy is not None:
        summary["ingestion_eligibility"] = {
            "source_hashes": source_policy.source_hashes,
            "company_saved_count": None,
            "limitations": "Serper source gate only; no DB, suppression or condition evaluation",
        }
        private["ingestion_source_hashes"] = source_policy.source_hashes
    grouped: dict[str, list[set[str]]] = {}
    for run in private["runs"]:
        provenance = run["provenance"]
        key = digest([provenance[k] for k in ("source", "query", "region")])
        if provenance["status"] == "COMPLETED":
            grouped.setdefault(key, []).append({row["raw_hash"] for row in run["observations"]})
    summary["raw_observation_stability"] = [
        {"query_group_hash": key, **stability(sets)} for key, sets in grouped.items()
    ]
    return summary, private


def stability(sets: list[set[str]]) -> dict[str, Any]:
    union = set().union(*sets) if sets else set()
    counts = Counter(key for run in sets for key in run)
    denominator = len(union)
    sufficient = len(sets) >= 2 and denominator > 0
    return {
        "run_count": len(sets),
        "union": denominator,
        "intersection": sum(n == len(sets) for n in counts.values()) if sufficient else None,
        "intersection_rate": sum(n == len(sets) for n in counts.values()) / denominator
        if sufficient
        else None,
        "repeat_discovery_rate": sum(n >= 2 for n in counts.values()) / denominator
        if sufficient
        else None,
        "single_run_rate": sum(n == 1 for n in counts.values()) / denominator
        if sufficient
        else None,
        "identity_truth": "RAW_OBSERVATION_HASH_ONLY_NOT_ENTITY_TRUTH",
    }


def read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 5_000_000:
        raise ValueError("Input must be <= 5 MB")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Input must be a JSON object")
    return value
