"""Read private saved diagnostics; export anonymous status/reason aggregates only."""

import argparse
import hashlib
import json
from pathlib import Path

from offline_replay.form_operation import summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Do not overwrite the private source")
    raw = args.input.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    rows = data["companies"]
    if not isinstance(rows, list) or len(rows) != 17:
        parser.error("Expected the fixed 17-record saved diagnostic cohort")
    result = summarize(rows) | {"private_source_sha256": hashlib.sha256(raw).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
