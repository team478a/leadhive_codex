"""Opt-in acquisition of one public form and bounded same-origin text assets."""

import argparse
import json
import os
from pathlib import Path

from app.services.browser_input_snapshot import acquire_snapshot
from app.services.scraper import ScrapeError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("LEADHIVE_BROWSER_INPUT_ACQUISITION") != "1":
        parser.error("Acquisition is OFF. Explicit opt-in is required.")
    if args.output.exists() or args.request.stat().st_size > 100_000:
        parser.error("Use a new private output file and a bounded request file.")
    request = json.loads(args.request.read_text(encoding="utf-8"))
    allowed = {"formUrl", "termsConfirmed", "values", "choices", "consents"}
    if not isinstance(request, dict) or set(request) != allowed:
        parser.error("Invalid request schema.")
    if not isinstance(request["formUrl"], str) or request["termsConfirmed"] is not True:
        parser.error("A form URL and explicit terms confirmation are required.")
    for key in ("values", "choices"):
        if not isinstance(request[key], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in request[key].items()
        ):
            parser.error("Invalid input values.")
    if not isinstance(request["consents"], dict) or not all(
        isinstance(k, str)
        and isinstance(v, dict)
        and set(v) == {"label", "checked"}
        and isinstance(v["label"], str)
        and isinstance(v["checked"], bool)
        for k, v in request["consents"].items()
    ):
        parser.error("Invalid explicit consent.")
    try:
        result = acquire_snapshot(request["formUrl"], terms_confirmed=True)
    except ScrapeError as exc:
        print(f"Acquisition stopped: {exc.public_message}")
        return 2
    if result["bundle"] is not None:
        result["bundle"].update({k: request[k] for k in ("values", "choices", "consents")})
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False)
    print(f"{result['status']}; GET requests: {result['getRequests']}; no input or send.")
    return 0 if result["bundle"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
