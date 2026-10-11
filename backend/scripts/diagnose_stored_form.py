"""Inventory a private saved HTML form without network, browser input or database."""

import argparse
import json
from pathlib import Path

from app.services.static_form_diagnostics import diagnose_static_form


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.html.stat().st_size > 500_000 or args.output.exists():
        parser.error("Use bounded saved HTML and a new private output file.")
    result = diagnose_static_form(args.html.read_text(encoding="utf-8"))
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(f"{result['status']}; fields: {len(result['fields'])}; no network, input or send.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
