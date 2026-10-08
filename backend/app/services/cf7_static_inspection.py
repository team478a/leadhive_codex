"""Isolated non-authoritative inspection, without fetching or retaining website text."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StaticInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["CF7_CANDIDATE", "NOT_CF7", "FORM_MISSING"]
    form_count: int = Field(ge=0, le=20)
    version: str | None
    form_id_valid: bool
    markers_complete: bool
    method_is_post: bool
    enctype_supported: bool
    missing_names: int = Field(ge=0, le=10000)
    file_inputs: int = Field(ge=0, le=10000)
    unsupported_controls: int = Field(ge=0, le=10000)
    rest_link_same_origin: bool
    base_override: bool
    execution_allowed: Literal[False]
    eligible_for_approval: Literal[False]


def validate_saved(value: object) -> dict | None:
    if isinstance(value, dict) and value.get("status") in {"PARSE_FAILED", "LIMIT_EXCEEDED"}:
        return {
            "status": value["status"],
            "execution_allowed": False,
            "eligible_for_approval": False,
        }
    try:
        parsed = StaticInspection.model_validate(value)
        if parsed.version is not None and not re.fullmatch(
            r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}", parsed.version
        ):
            return None
        return parsed.model_dump()
    except (ValueError, TypeError):
        return None


def inspect_isolated(html: str, url: str, index: int) -> dict:
    failed = {"status": "PARSE_FAILED", "execution_allowed": False, "eligible_for_approval": False}
    if len(html.encode("utf-8")) > 262144:
        return failed | {"status": "LIMIT_EXCEEDED"}
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("cf7_static_parser.py"))],
            input=json.dumps({"html": html, "url": url, "index": index}).encode(),
            capture_output=True,
            timeout=5,
            check=True,
            env={key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if len(result.stdout) > 2048:
            return failed
        return validate_saved(json.loads(result.stdout)) or failed
    except (subprocess.SubprocessError, OSError, ValueError):
        return failed
