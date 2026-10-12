"""Explicit private-file input; reuses offline replay network deny and write-once output."""

import argparse
import json
import time
from pathlib import Path

from offline_replay.cli import deny_network, protect_private_output, write_once
from offline_replay.feedback import compare


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated feedback comparison; no DB or API")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with deny_network():
            if args.input.resolve() == args.output.resolve() or args.output.exists():
                raise ValueError("Distinct new output required")
            if args.input.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Input size limit")
            protect_private_output(args.input, args.checkout)
            bundle = json.loads(args.input.read_text(encoding="utf-8-sig"))
            start = time.perf_counter()
            report = compare(bundle, args.project)
            report["offline_lab_seconds"] = time.perf_counter() - start
            # Aggregate only: no IDs, URLs, evidence, prompt text or raw values.
            write_once(args.output, report)
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        parser.exit(2, "Feedback lab stopped. Check private input and project scope.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
