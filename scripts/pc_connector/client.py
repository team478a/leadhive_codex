"""Bounded, read-only cloud review transport. No browser or dispatch capability."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

MAX_BYTES = 2_000_000
PAGE_SIZE = 50
MAX_PAGES = 3


class ConnectorError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ConnectorError(
            "Redirect refused; configure the final trusted server URL."
        )


def origin(value: str, local: bool = False) -> str:
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ConnectorError("Invalid server origin.")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ConnectorError("Invalid server origin.") from None
    if (
        not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ConnectorError("Use a server origin without credentials, path or query.")
    loopback = parts.hostname in {"127.0.0.1", "::1"}
    if parts.scheme != "https" and not (local and loopback and parts.scheme == "http"):
        raise ConnectorError(
            "HTTPS required; HTTP is permitted only for explicit loopback tests."
        )
    if parts.scheme == "https" and port not in {None, 443}:
        raise ConnectorError("Cloud HTTPS must use port 443.")
    return value.rstrip("/")


def read_page(
    opener, server: str, project: UUID, token: str, offset: int
) -> list[dict]:
    query = urlencode({"limit": PAGE_SIZE, "offset": offset})
    request = Request(
        f"{server}/api/agent/projects/{project}/approval-requests?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=15) as response:
            if (
                response.status != 200
                or response.headers.get_content_type() != "application/json"
            ):
                raise ConnectorError("Unexpected response; no data exported.")
            content = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        # Never include server response bodies, URLs or Authorization in errors.
        raise ConnectorError(
            f"Server refused the request (HTTP {error.code})."
        ) from None
    except (URLError, TimeoutError, OSError):
        raise ConnectorError(
            "Connection failed; check the server and credential configuration."
        ) from None
    if len(content) > MAX_BYTES:
        raise ConnectorError("Response size limit exceeded.")
    try:
        rows = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise ConnectorError("Invalid JSON response.") from None
    if (
        not isinstance(rows, list)
        or len(rows) > PAGE_SIZE
        or any(not isinstance(r, dict) for r in rows)
    ):
        raise ConnectorError("Unexpected list response.")
    return rows


def review_manifest(rows: list[dict], project: UUID) -> dict:
    """Project-bound metadata only. Never export a runnable task, message or sender."""
    items = []
    seen = set()
    for row in rows:
        try:
            request_id = str(UUID(row["id"]))
            if UUID(row["project_id"]) != project:
                raise ValueError()
            if request_id in seen:
                raise ValueError()
            seen.add(request_id)
            if row["channel"] != "form" or row["delivery_method"] != "form_codex":
                continue
            snapshot = row["payload_snapshot"]
            if (
                not isinstance(snapshot, dict)
                or row["canonicalization_version"] != "json-v1"
            ):
                raise ValueError()
            digest = hashlib.sha256(
                json.dumps(
                    snapshot,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            if digest != row["payload_hash"]:
                raise ValueError()
            version = row["payload_version"]
            if type(version) is not int or version < 1:
                raise ValueError()
            status = row["status"]
            if status not in {
                "PENDING",
                "APPROVED",
                "REJECTED",
                "EXPIRED",
                "REVOKED",
                "CONSUMED",
            }:
                raise ValueError()
            expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None:
                raise ValueError()
            if expires <= datetime.now(timezone.utc) and status in {
                "PENDING",
                "APPROVED",
            }:
                status = "EXPIRED"
            if status == "APPROVED" and (
                row.get("approved_payload_hash") != digest
                or row.get("approved_payload_version") != version
                or not row.get("approved_by_user_id")
                or not row.get("approved_at")
            ):
                raise ValueError()
            items.append(
                {
                    "request_id": request_id,
                    "project_id": str(project),
                    "status_at_read": status,
                    "payload_hash": digest,
                    "payload_version": version,
                    "expires_at": expires.isoformat(),
                    "execution_allowed": False,
                }
            )
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise ConnectorError(
                "Invalid project, duplicate or payload binding; no data exported."
            ) from None
    return {
        "schema": "leadhive-pc-review-v1",
        "project_id": str(project),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "execution_allowed": False,
        "items": items,
        "instructions": "Review metadata only. Do not open a form, fill, approve or submit.",
    }


def collect(
    server: str, project: UUID, token: str, pages: int = 1, local: bool = False
) -> dict:
    server = origin(server, local)
    if not 1 <= pages <= MAX_PAGES:
        raise ConnectorError("Page budget must be between 1 and 3.")
    if (
        not token.startswith("lh_agent_")
        or len(token) > 200
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)
    ):
        raise ConnectorError("A valid dedicated Agent credential is required.")
    # No cookie jar, redirect following or ambient proxy credentials.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    rows = []
    limit_reached = False
    for index in range(pages):
        batch = read_page(opener, server, project, token, index * PAGE_SIZE)
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        limit_reached = index == pages - 1
    result = review_manifest(rows, project)
    result.update(
        raw_records_read=len(rows),
        request_count=index + 1,
        possibly_truncated=limit_reached,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read LeadHive cloud review metadata. Never send."
    )
    parser.add_argument("--server", required=True)
    parser.add_argument("--project", type=UUID, required=True)
    parser.add_argument("--pages", type=int, choices=range(1, MAX_PAGES + 1), default=1)
    parser.add_argument("--allow-loopback-http", action="store_true")
    parser.add_argument(
        "--output", type=Path, help="Optional private metadata JSON; must not exist."
    )
    args = parser.parse_args()
    try:
        result = collect(
            args.server,
            args.project,
            os.environ.get("LEADHIVE_AGENT_TOKEN", ""),
            args.pages,
            args.allow_loopback_http,
        )
        if args.output:
            descriptor = os.open(
                args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(result, output, ensure_ascii=False, indent=2)
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "request_count",
                        "raw_records_read",
                        "possibly_truncated",
                        "execution_allowed",
                    )
                }
                | {"form_codex_review_records": len(result["items"])}
            )
        )
        return 0
    except (ConnectorError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, ConnectorError)
            else "Cannot create private output file."
        )
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
