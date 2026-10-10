"""Explicit GET experiment, private snapshots, anonymous aggregates. No DB imports."""

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

from app.config import settings
from app.services.scraper import FetchedPage, extract_page
from app.services.scrapling_adapter import Mode, acquire, acquisition_failure, probe
from offline_replay.scrapling_metrics import FIELDS, summarize


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--live-get", action="store_true")
    parser.add_argument("--replay-dir", type=Path)
    args = parser.parse_args()
    if not settings.scrapling_probe_enabled or not 1 <= args.limit <= 100:
        parser.error("Enable SCRAPLING_PROBE_ENABLED and select 1..100 cases")
    if args.live_get == bool(args.replay_dir):
        parser.error("Select exactly one of --live-get or --replay-dir")
    root = Path(__file__).resolve().parents[2]
    if args.private_dir.resolve().is_relative_to(root):
        parser.error("Private output must be outside the repository")
    args.private_dir.mkdir(parents=True, exist_ok=False)
    if args.aggregate.exists():
        parser.error("Do not overwrite comparison results")
    source_hash = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    truth_file = json.loads(args.truth.read_text(encoding="utf-8")) if args.truth else {}
    if truth_file and truth_file.get("source_sha256") != source_hash:
        parser.error("Human truth must be bound to the exact CSV source hash")
    truth = truth_file.get("cases", {})
    with args.csv.open(encoding="utf-8-sig", newline="") as stream:
        candidates = list(csv.DictReader(stream))[: args.limit]
    manifest = {
        "source_sha256": source_hash,
        "cases": {
            f"case-{i:03}": candidate.get("URL", candidate.get("website_url", ""))
            for i, candidate in enumerate(candidates, 1)
        },
    }
    write_new(args.private_dir / "manifest.json", manifest)
    replay_manifest = {}
    if args.replay_dir and (args.replay_dir / "manifest.json").exists():
        replay_manifest = json.loads(
            (args.replay_dir / "manifest.json").read_text(encoding="utf-8")
        )
        if replay_manifest.get("source_sha256") != source_hash:
            parser.error("Replay source hash mismatch")
    results = []
    for index, candidate in enumerate(candidates, 1):
        case_id = f"case-{index:03}"
        url = candidate.get("URL", candidate.get("website_url", ""))
        row: dict = {"case_id": case_id, "methods": {}, "truth": truth.get(case_id, {})}
        try:
            if args.live_get:
                page, elapsed, calls = acquire(url)
            else:
                saved = json.loads(
                    (args.replay_dir / f"{case_id}-snapshot.json").read_text(encoding="utf-8")
                )
                page = FetchedPage(saved["url"], saved["html"])
                if (
                    saved.get("requested_url", replay_manifest.get("cases", {}).get(case_id)) != url
                    or saved["html_sha256"] != hashlib.sha256(page.html.encode()).hexdigest()
                ):
                    raise ValueError("SNAPSHOT_MISMATCH")
                elapsed, calls = 0.0, 0
            row.update(html_acquired=True, external_gets=calls, acquisition_seconds=elapsed)
            write_new(
                args.private_dir / f"{case_id}-snapshot.json",
                {
                    "url": page.url,
                    "requested_url": url,
                    "html": page.html,
                    "html_sha256": hashlib.sha256(page.html.encode()).hexdigest(),
                },
            )
            started = time.monotonic()
            try:
                data = extract_page(page.html, page.url)
                row["methods"]["current"] = {
                    "success": True,
                    "fields": {f: getattr(data, f) for f in FIELDS},
                    "elapsed_seconds": elapsed + time.monotonic() - started,
                }
            except Exception:
                row["methods"]["current"] = {
                    "success": False,
                    "reason": "EXTRACTION_FAILED",
                    "elapsed_seconds": elapsed,
                }
            modes: tuple[Mode, ...] = ("scrapling_static", "scrapling_dynamic_replay")
            for method in modes:
                result = probe(page, method)
                row["methods"][method] = {
                    "success": result.data is not None,
                    "reason": result.failure_reason,
                    "fields": {f: getattr(result.data, f) for f in FIELDS} if result.data else {},
                    "elapsed_seconds": elapsed + result.elapsed_seconds,
                    "blocked_requests": result.blocked_browser_requests,
                }
        except Exception as exc:
            row.update(
                html_acquired=False,
                acquisition_reason=acquisition_failure(exc),
                external_gets=getattr(exc, "probe_external_gets", 0),
                acquisition_seconds=getattr(exc, "probe_elapsed_seconds", None),
            )
            row["methods"] = {
                method: {
                    "success": False,
                    "reason": row["acquisition_reason"],
                    "elapsed_seconds": row["acquisition_seconds"],
                }
                for method in ("current", "scrapling_static", "scrapling_dynamic_replay")
            }
        write_new(args.private_dir / f"{case_id}-result.json", row)
        results.append(row)
        print(f"{case_id}: acquired={row['html_acquired']}", flush=True)
    aggregate = summarize(results)
    aggregate.update(
        source_sha256=source_hash,
        scope="root HTML shared acquisition; offline inline-JS replay; not full site crawl",
        human_truth_supplied=bool(truth),
        production_enabled=False,
    )
    write_new(args.aggregate, aggregate)


if __name__ == "__main__":
    main()
