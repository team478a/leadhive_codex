"""Read-only inventory of saved article discovery hits; never fetches article URLs."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

EXTRACTOR_VERSION = "article-rule-1"
DATABASE_URL_ENV = "ARTICLE_EXTRACTION_READONLY_DATABASE_URL"


def canonical_article_url(value: str | None) -> str:
    """Normalize URL identity without following it or exposing it in the report."""
    if not value:
        return ""
    try:
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port
        is_default_port = port is None or (scheme, port) in {("http", 80), ("https", 443)}
        netloc = host if is_default_port else f"{host}:{port}"
        path = (parsed.path or "").rstrip("/")
        return urlunsplit((scheme, netloc, path, parsed.query, ""))
    except (UnicodeError, ValueError):
        return "invalid:" + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def aggregate_rows(rows: list[tuple[str, str, str | None, bool]]) -> dict:
    """Aggregate (project, reason, article URL, extracted-at-current-version) rows."""
    projects: dict[str, dict] = {}
    for project_id, reason, article_url, extracted in rows:
        project = projects.setdefault(
            str(project_id),
            {
                "article_hit_count": 0,
                "reason_counts": defaultdict(int),
                "urls": set(),
                "unextracted_hit_count": 0,
                "unextracted_urls": set(),
            },
        )
        url_key = canonical_article_url(article_url)
        project["article_hit_count"] += 1
        project["reason_counts"][reason or "UNKNOWN"] += 1
        project["urls"].add(url_key)
        if not extracted:
            project["unextracted_hit_count"] += 1
            project["unextracted_urls"].add(url_key)

    result = []
    for project_id, values in sorted(projects.items()):
        result.append(
            {
                "project_id": project_id,
                "article_hit_count": values["article_hit_count"],
                "reason_counts": dict(sorted(values["reason_counts"].items())),
                "unique_article_url_count": len(values["urls"]),
                "unextracted_same_version_hit_count": values["unextracted_hit_count"],
                "unextracted_same_version_unique_url_count": len(values["unextracted_urls"]),
            }
        )
    return {
        "schema_version": "article-extraction-inventory-v1",
        "extractor_version": EXTRACTOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "projects": result,
    }


def read_inventory(database_url: str) -> dict:
    psycopg = importlib.import_module("psycopg")

    query = """
        SELECT j.project_id::text, h.classification_reason, h.snapshot->>'link',
               (e.id IS NOT NULL)
        FROM collection_discovery_hits AS h
        JOIN collection_jobs AS j ON j.id = h.collection_job_id
        LEFT JOIN collection_article_extractions AS e
          ON e.project_id = j.project_id
         AND e.discovery_hit_id = h.id
         AND e.extractor_version = %s
        WHERE j.source = 'serper'
          AND h.classification = 'ARTICLE'
        ORDER BY j.project_id, h.classification_reason, h.id
    """
    try:
        with psycopg.connect(
            database_url,
            autocommit=False,
            options="-c default_transaction_read_only=on",
        ) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                read_only = connection.execute("SHOW transaction_read_only").fetchone()[0]
                if read_only != "on":
                    raise RuntimeError("Read-only database transaction unavailable")
                rows = connection.execute(query, (EXTRACTOR_VERSION,)).fetchall()
    except psycopg.Error:
        raise RuntimeError("Read-only inventory query failed") from None
    return aggregate_rows(rows)


def write_once(path: Path, report: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only summary of saved ARTICLE hits; no article/network access"
    )
    parser.add_argument("--output", type=Path, help="New output path; defaults to stdout")
    args = parser.parse_args(argv)
    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        parser.exit(2, f"Set {DATABASE_URL_ENV} to an explicitly selected database URL.\n")
    try:
        report = read_inventory(database_url)
        if args.output:
            write_once(args.output, report)
        else:
            json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"Inventory stopped ({type(exc).__name__}). No report was written.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
