"""Audit-only execution of the current scheduler against synthetic I/O boundaries.

No application imports, DB, credentials, network or dispatch. Proposal AST changes
exist only in this replay process; production source is never written.
"""

import ast
import copy
import hashlib
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from offline_replay.cli import deny_network


def _function(source: str, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"Audited function missing: {name}")
    return copy.deepcopy(matches[0])


def replay(
    source: str,
    pages: Mapping[tuple[str, int], list[dict[str, str]] | str],
    *,
    keywords: list[str],
    target: int = 100,
    page_size: int = 10,
    budget: int = 50,
    grace: int = 1,
) -> dict[str, Any]:
    if not (1 <= page_size <= 100 and 1 <= budget <= 50 and 1 <= grace <= 3):
        raise ValueError("Replay limits exceed the audited budget")
    original = copy.deepcopy(pages)
    for value in pages.values():
        if isinstance(value, str):
            if value != "ERROR":
                raise ValueError("Unknown synthetic source outcome")
            continue
        for row in value:
            if set(row) != {"key", "state"} or row["state"] not in {
                "MATCH",
                "REVIEW_REQUIRED",
                "NO_MATCH",
                "EXCLUDED",
            }:
                raise ValueError("Unknown synthetic candidate")
    run = _function(source, "run")
    if grace != 1:
        matches = []
        for node in ast.walk(run):
            if (
                isinstance(node, ast.If)
                and ast.unparse(node.test) == "not after_inventory.keys() - before_inventory.keys()"
            ):
                matches.append(node)
        if len(matches) != 1:
            raise ValueError("Production no-growth boundary changed; re-audit required")
        matches[0].test = ast.parse(
            "no_growth_stop(keyword, after_inventory.keys() - before_inventory.keys())", mode="eval"
        ).body

    inventory: dict[str, str] = {}
    requests: list[dict[str, Any]] = []
    consumed: list[dict[str, str]] = []
    ingested: list[dict[str, str]] = []
    streaks: dict[str, int] = {}
    job = SimpleNamespace(
        id=UUID(int=1),
        project_id=UUID(int=2),
        payload={},
        failed_count=0,
        processed_count=0,
        success_count=0,
    )
    db = SimpleNamespace(commit=lambda: None)

    class SourceError(Exception):
        public_message = "SYNTHETIC_SOURCE_ERROR"

    def search(keyword, region, size, page):
        requests.append({"query": keyword, "page": page, "requested_size": size})
        value = pages.get((keyword, page), [])
        if isinstance(value, str):
            raise SourceError()
        selected = copy.deepcopy(value[:size])
        consumed.extend(selected)
        return [
            SimpleNamespace(
                **row,
                company_name=row["key"],
                website_url=f"https://{row['key']}.example",
                address="",
            )
            for row in selected
        ]

    def save(db, collection, candidates, keyword):
        for candidate in candidates:
            row = {"key": candidate.key, "state": candidate.state}
            ingested.append(row)
            if candidate.state != "EXCLUDED":
                inventory.setdefault(candidate.key, candidate.state)

    def no_growth_stop(keyword, growth):
        streaks[keyword] = 0 if growth else streaks.get(keyword, 0) + 1
        return streaks[keyword] >= grace

    def canonicalize(url):
        return url, url.split("//", 1)[1].split(".", 1)[0]

    environment: dict[str, Any] = {
        "UUID": UUID,
        "REQUEST_BUDGET": budget,
        "PAGE_SIZE": page_size,
        "collection_inventory": lambda db, job, conditions: dict(inventory),
        "start_job": lambda *args, **kwargs: SimpleNamespace(id=UUID(int=3)),
        "fail_job": lambda *args: None,
        "capture_usage": lambda: nullcontext([]),
        "persist_usage": lambda *args, **kwargs: None,
        "ExternalServiceError": SourceError,
        "search_serper_page": search,
        "save_candidates": save,
        "canonicalize_url": canonicalize,
        "is_duplicate": lambda db, project, candidate: candidate.key in inventory,
        "is_suppressed": lambda db, project, candidate: candidate.state == "EXCLUDED",
        "is_aggregator_domain": lambda domain: False,
        "no_growth_stop": no_growth_stop,
    }
    tree = ast.fix_missing_locations(
        ast.Module(body=[_function(source, "bounded_candidates"), run], type_ignores=[])
    )
    with deny_network():
        exec(compile(tree, "<local-audited-scheduler>", "exec"), environment)
        environment["run"](
            db,
            job,
            {"keywords": keywords, "region": "大阪府・兵庫県", "target_count": target},
            None,
            lambda: False,
        )
    assert pages == original
    return {
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "configuration": {
            "page_size": page_size,
            "request_budget": budget,
            "no_growth_grace": grace,
            "target": target,
        },
        "synthetic_raw_hits": len(consumed),
        "synthetic_ingested_hits": len(ingested),
        "retrieved_but_not_ingested": len(consumed) - len(ingested),
        "synthetic_unique_candidates": len(inventory),
        "synthetic_match_count": sum(value == "MATCH" for value in inventory.values()),
        "requests": requests,
        "progress": job.payload["collection_progress"],
        "human_precision": None,
        "official_site_accuracy": None,
        "contact_discovery_rate": None,
        "api_cost": None,
    }


def rows(start: int, count: int, state: str = "MATCH") -> list[dict[str, str]]:
    return [{"key": f"entity-{index}", "state": state} for index in range(start, start + count)]


def legacy_search_replay(
    source: str, responses: dict[tuple[int, int], list[dict]], requested: int
) -> dict[str, Any]:
    """Execute the locally pinned legacy search function with a synthetic POST stub.

    This is the Serper service boundary only, not legacy UI/collector ingestion.
    Legacy source is never copied into this repository or imported as an app.
    """
    function = _function(source, "search_serper")
    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(function)):
        raise ValueError("Legacy function changed; re-audit required")
    calls: list[dict[str, int]] = []

    def post(url, **kwargs):
        payload = kwargs["json"]
        calls.append({"num": payload["num"], "page": payload["page"]})
        data = copy.deepcopy(responses.get((payload["num"], payload["page"]), []))
        return SimpleNamespace(status_code=200, json=lambda: {"organic": data})

    environment: dict[str, Any] = {
        "requests": SimpleNamespace(post=post),
        "logger": SimpleNamespace(error=lambda *args: None),
    }
    tree = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    with deny_network():
        exec(compile(tree, "<audited-local-legacy-serper>", "exec"), environment)
        result = environment["search_serper"]("SYNTHETIC_NOT_A_KEY", "SYNTHETIC", num=requested)
    urls = [row["url"] for row in result if row.get("url")]
    return {
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "synthetic_raw_hits": len(urls),
        "synthetic_unique_urls": len(set(urls)),
        "requests": calls,
        "human_precision": None,
        "api_cost": None,
        "boundary": "SERPER_SERVICE_ONLY_NOT_LEGACY_APPLICATION",
    }


def experiments(source: str) -> dict[str, Any]:
    cases: dict[str, tuple[dict[tuple[str, int], list[dict[str, str]] | str], dict[str, Any]]] = {
        "duplicate_plateau_then_new_page": (
            {("q", 1): rows(0, 10), ("q", 2): rows(0, 10), ("q", 3): rows(10, 10)},
            {},
        ),
        "excluded_first_page_then_valid": (
            {("q", 1): rows(0, 10, "EXCLUDED"), ("q", 2): rows(10, 10)},
            {},
        ),
        "review_growth_is_not_exhaustion": (
            {("q", 1): rows(0, 10, "REVIEW_REQUIRED"), ("q", 2): rows(10, 10)},
            {},
        ),
        "target_truncates_uningested_raw": ({("q", 1): rows(0, 10)}, {"target": 1}),
        "empty_tail_extra_cost": ({("q", 1): rows(0, 10)}, {}),
        "source_error_is_not_exhaustion": ({("q", 1): rows(0, 10), ("q", 2): "ERROR"}, {}),
        "global_budget_starves_later_query": (
            {
                **{("q", page): rows(page * 10, 10, "REVIEW_REQUIRED") for page in range(1, 51)},
                ("later", 1): rows(1000, 10),
            },
            {"keywords": ["q", "later"]},
        ),
    }
    results: dict[str, Any] = {}
    for name, (pages, options) in cases.items():
        parameters: dict[str, Any] = {"keywords": ["q"], **options}
        baseline = replay(source, pages, **parameters)
        proposal = replay(source, pages, grace=2, **parameters)
        results[name] = {"baseline": baseline, "proposal_grace_2": proposal}
    dense = {("q", 1): rows(0, 20), ("q", 2): rows(20, 20)}
    results["page_size_contract_sensitivity"] = {
        "baseline": replay(source, dense, keywords=["q"], target=40),
        "proposal_size_20": replay(source, dense, keywords=["q"], target=40, page_size=20),
        "warning": (
            "Synthetic explicit response fixture; not proof that Serper returns 20 "
            "or identical page boundaries."
        ),
    }
    return {
        "schema_version": "phase2c-offline-scheduler-v1",
        "dataset_kind": "SYNTHETIC",
        "evaluation": "CONTROL_FLOW_ONLY_NOT_REAL_PRECISION",
        "cases": results,
        "safety": {
            "external_requests": 0,
            "db_writes": 0,
            "human_labels_created": 0,
            "approvals": 0,
            "email_sent": 0,
            "form_sent": 0,
        },
    }


def main() -> None:
    import argparse
    import json

    from offline_replay.cli import git_source, write_once
    from offline_replay.comparison import CURRENT_COMMIT, LEGACY_COMMIT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = git_source(root, CURRENT_COMMIT, "backend/app/services/target_collection.py")
    report = experiments(source)
    report["current_commit"] = CURRENT_COMMIT
    report["legacy_commit"] = LEGACY_COMMIT
    if arguments.legacy_root:
        legacy_source = git_source(
            arguments.legacy_root, LEGACY_COMMIT, "server/services/serper_search.py"
        )
        hits = [{"link": f"https://entity-{i}.example/", "title": "Synthetic"} for i in range(10)]
        response = (
            hits
            + hits
            + [
                {"link": f"https://entity-{i}.example/", "title": "Synthetic"}
                for i in range(10, 20)
            ]
        )
        result = legacy_search_replay(legacy_source, {(30, 1): response}, 30)
        result["warning"] = (
            "Explicit synthetic size-30 provider response. "
            "Not evidence of real yield or ranking stability."
        )
        report["legacy_service_contract_case"] = result
    if arguments.output:
        write_once(arguments.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
