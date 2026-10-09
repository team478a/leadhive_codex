"""CLI for local fixed-SHA replay. Never fetches repositories or opens URLs."""

import argparse
import hashlib
import json
import re
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from offline_replay.comparison import CURRENT_COMMIT, LEGACY_COMMIT, Policies, compare, read_json
from offline_replay.source_policy import SourcePolicy


@contextmanager
def deny_network():
    """Fail closed even if an offline projection later attempts Python network I/O."""
    methods = ("socket", "create_connection", "getaddrinfo", "gethostbyname")
    original = {name: getattr(socket, name) for name in methods}

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Network is forbidden in offline replay")

    try:
        for name in methods:
            setattr(socket, name, denied)
        yield
    finally:
        for name, function in original.items():
            setattr(socket, name, function)


def git_source(root: Path, commit: str, relative: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{relative}"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            "Required baseline source is unavailable locally; no fetch attempted"
        ) from exc
    return result.stdout.decode("utf-8-sig")


def write_once(path: Path, payload: dict[str, Any]) -> None:
    # Never overwrite a previous raw replay or write through a pre-existing output symlink.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def protect_private_output(path: Path, current_root: Path) -> None:
    try:
        path.resolve().relative_to(current_root.resolve())
    except ValueError:
        return  # Outside the current checkout. Caller must keep this artifact private.
    result = subprocess.run(
        ["git", "-C", str(current_root), "check-ignore", "--quiet", "--", str(path.resolve())],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError("Private observations must be outside Git or under an ignored directory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline Serper boundary comparison; no collection"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--current-root", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--current-commit", default=CURRENT_COMMIT)
    parser.add_argument("--legacy-commit", default=LEGACY_COMMIT)
    parser.add_argument("--include-ingestion-eligibility", action="store_true")
    args = parser.parse_args(argv)
    if any(
        not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (args.current_commit, args.legacy_commit)
    ):
        parser.error("Baselines must be explicit full lowercase commit SHAs")
    paths = [args.input.resolve(), args.summary.resolve(), args.private_output.resolve()]
    if len(set(paths)) != 3 or args.summary.exists() or args.private_output.exists():
        parser.error("Input and outputs must be distinct; outputs must not already exist")
    try:
        with deny_network():
            started_at = datetime.now(timezone.utc).isoformat()
            protect_private_output(args.private_output, args.current_root)
            protect_private_output(args.private_output, args.legacy_root)
            fixture = read_json(args.input)
            policies = Policies(
                git_source(args.legacy_root, args.legacy_commit, "server/services/aggregator.py"),
                git_source(
                    args.current_root, args.current_commit, "backend/app/services/collection.py"
                ),
                git_source(
                    args.current_root, args.current_commit, "backend/app/services/scraper.py"
                ),
                source_commits={"legacy": args.legacy_commit, "current": args.current_commit},
            )
            source_policy = None
            if args.include_ingestion_eligibility:
                source_policy = SourcePolicy(
                    *[
                        git_source(
                            args.current_root,
                            args.current_commit,
                            f"backend/app/services/{name}.py",
                        )
                        for name in (
                            "collection",
                            "scraper",
                            "presence_platforms",
                            "collection_discovery",
                        )
                    ]
                )
            start = time.perf_counter()
            summary, private = compare(fixture, policies, source_policy=source_policy)
            summary["offline_processing_seconds"] = time.perf_counter() - start
            summary["started_at"] = started_at
            summary["finished_at"] = datetime.now(timezone.utc).isoformat()
            summary["runner_source_hashes"] = {
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in ("cli.py", "comparison.py", "source_policy.py")
            }
            write_once(args.private_output, private)
            write_once(args.summary, summary)
    except (ValueError, OSError, RuntimeError) as exc:
        # Do not print raw data, file contents, provider error strings or credentials.
        parser.exit(
            2, f"Offline replay stopped ({type(exc).__name__}). Check input and local baselines.\n"
        )
    print("Offline replay completed. Human precision and contact metrics remain unmeasured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
