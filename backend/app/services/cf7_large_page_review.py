"""Bounded saved-page diagnostics only; not an inspection/approval substitute."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LargePageReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["REVIEW_ONLY"]
    whole_page_scanned: Literal[True]
    form_count: int = Field(ge=0, le=20)
    cf7_marker: bool
    version: str | None
    captcha_marker_detected: bool
    base_override: bool
    external_control: bool
    rest_link_same_origin: bool
    extra_hidden: int | None = Field(ge=0, le=100)
    repeated_names: int | None = Field(ge=0, le=100)
    radio_controls: int | None = Field(ge=0, le=100)
    select_controls: int | None = Field(ge=0, le=100)
    file_inputs: int | None = Field(ge=0, le=100)
    missing_names: int | None = Field(ge=0, le=100)
    permission_status: Literal["UNKNOWN"]
    human_review_required: Literal[True]
    execution_allowed: Literal[False]
    eligible_for_approval: Literal[False]


def review_saved_large_page(html: str, url: str, index: int) -> dict:
    failed = {
        "status": "PARSE_FAILED",
        "human_review_required": True,
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
    if len(html.encode("utf-8")) > 1048576:
        return failed | {"status": "LIMIT_EXCEEDED"}
    if type(index) is not int or not 0 <= index < 20:
        return failed
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("cf7_static_parser.py")),
                "--large-review-only",
            ],
            input=json.dumps(
                {"html": html, "url": url, "index": index}, ensure_ascii=False
            ).encode(),
            capture_output=True,
            timeout=5,
            check=True,
            env={key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if len(result.stdout) > 32000:
            return failed
        parsed = LargePageReview.model_validate(json.loads(result.stdout))
        if parsed.version is not None and not re.fullmatch(
            r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}", parsed.version
        ):
            return failed
        return parsed.model_dump()
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        return failed
