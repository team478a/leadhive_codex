"""Private, immutable Phase 5E artifacts; no database, network or runtime changes."""

import argparse
import json
from pathlib import Path

from offline_replay.cli import deny_network, protect_private_output, write_once
from offline_replay.evaluation_history import checkpoint, observation, trend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline evaluation checkpoint and trend")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument("--explanation", type=Path)
    parser.add_argument("--explanation-output", type=Path)
    args = parser.parse_args(argv)
    try:
        with deny_network():
            if bool(args.previous) != bool(args.comparison_output):
                raise ValueError("Previous and comparison output required together")
            if bool(args.explanation) != bool(args.explanation_output) or (
                args.explanation and not args.previous
            ):
                raise ValueError("Explanation requires a comparison and distinct output")
            inputs = [p for p in (args.input, args.previous, args.explanation) if p]
            outputs = [
                p for p in (args.output, args.comparison_output, args.explanation_output) if p
            ]
            if len({p.resolve() for p in inputs + outputs}) != len(inputs + outputs):
                raise ValueError("Distinct paths required")
            for path in inputs + outputs:
                protect_private_output(path, args.checkout)
            if any(p.exists() for p in outputs):
                raise ValueError("New output required")

            def read(path):
                if path.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError("Input size limit")
                return json.loads(path.read_text(encoding="utf-8-sig"))

            current = checkpoint(read(args.input), args.project, start=args.start, end=args.end)
            comparison = trend(read(args.previous), current) if args.previous else None
            explanation = None
            if args.explanation:
                assert comparison is not None
                explanation = observation(comparison, **read(args.explanation))
            # Validate every input before writing; exclusive creation prevents replacement.
            write_once(args.output, current)
            if args.comparison_output:
                assert comparison is not None
                write_once(args.comparison_output, comparison)
            if args.explanation_output:
                assert explanation is not None
                write_once(args.explanation_output, explanation)
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        parser.exit(2, "Evaluation history stopped. Check private files, interval and scope.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
