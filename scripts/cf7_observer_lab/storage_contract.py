"""Offline, non-authoritative storage contract. No DB, fetch or application imports."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Literal, Self
from uuid import UUID

import observer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from transport import TransportBlocked, public_addresses

PAGE = "https://managed.example/contact/"
LIMIT = 32768
REASONS = {
    "REVIEW_REQUIRED": frozenset({"STATIC_ONLY_UNVERIFIED"}),
    "BLOCKED": frozenset({"SALES_PROHIBITED"}),
    "HUMAN_REQUIRED": frozenset(
        {
            "CAPTCHA_DETECTED",
            "BASE_URL_OVERRIDE",
            "CUSTOM_EXECUTION",
            "EXTERNAL_FORM_CONTROLS",
            "FORM_ACTION",
            "CONTROL_STATE",
            "LABEL_UNVERIFIED",
            "ACCEPTANCE_UNSUPPORTED",
        }
    ),
    "UNSUPPORTED": frozenset(
        {
            "PAGE_URL_POLICY",
            "HTTP_METADATA",
            "BODY_BOUNDS",
            "HTML_ENCODING_OR_ATTRIBUTES",
            "HTML_CHARSET",
            "DUPLICATE_IDS",
            "FORM_COUNT_OR_TYPE",
            "FORM_METHOD",
            "STATIC_CONFIG_OR_ROOT",
            "UNNAMED_CONTROL",
            "FIELD_NAMES_OR_LIMIT",
            "HIDDEN_OR_TOKEN",
            "VERSION_OR_ID_BINDING",
            "CONTROL_TYPE_OR_NAME",
            "CHECKBOX_VALUE",
            "CONTROL_COUNT",
        }
    ),
}
SENSITIVE = re.compile(
    r"(?i)(secret|password|api[-_ ]?key|bearer|authorization|cookie|token|smtp|sk-proj-)"
    r"|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\d[\d ()+-]{7,}\d"
)


class ContractBlocked(ValueError):
    """Fixed diagnostics only; do not include raw input in user-facing errors."""


class Frozen(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, revalidate_instances="always"
    )


class Binding(Frozen):
    project_id: UUID
    company_id: UUID
    company_project_id: UUID
    operation_job_id: UUID
    job_project_id: UUID
    run_id: UUID
    lease_worker_id: UUID
    initiated_by_user_id: UUID
    attempt_number: int = Field(ge=1, le=1000)
    operation_type: Literal["cf7_observation"] = "cf7_observation"
    target_url: Literal["https://managed.example/contact/"] = (
        "https://managed.example/contact/"
    )
    company_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        if (
            self.project_id != self.company_project_id
            or self.project_id != self.job_project_id
        ):
            raise ValueError("Project binding mismatch")
        if any(
            isinstance(value, UUID) and value.int == 0
            for value in self.__dict__.values()
        ):
            raise ValueError("Invalid binding ID")
        return self


class ControlSummary(Frozen):
    position: int = Field(ge=0, le=49)
    name: str = Field(max_length=100)
    label: str = Field(max_length=250)
    kind: Literal["text", "email", "tel", "textarea", "checkbox"]
    required: bool
    default_checked: bool
    redacted: bool
    truncated: bool

    @model_validator(mode="after")
    def privacy(self) -> Self:
        if SENSITIVE.search(self.name) or SENSITIVE.search(self.label):
            raise ValueError("Sensitive diagnostic text")
        return self


class StructureSummary(Frozen):
    form_count: Literal[1] = 1
    cf7_version: Literal["6.1.4"] = "6.1.4"
    mapping: Literal["HUMAN_REQUIRED"] = "HUMAN_REQUIRED"
    controls: tuple[ControlSummary, ...] = Field(min_length=3, max_length=50)

    @model_validator(mode="after")
    def positions(self) -> Self:
        if tuple(c.position for c in self.controls) != tuple(range(len(self.controls))):
            raise ValueError("Invalid diagnostic order")
        return self


class FetchSummary(Frozen):
    status: Literal[200] = 200
    media_type: Literal["text/html", "text/html; charset=utf-8"]
    body_bytes: int = Field(ge=1, le=65536)
    robots_bytes: int = Field(ge=1, le=16384)
    robots_decision: Literal["ALLOWED_OWNED_FIXTURE"] = "ALLOWED_OWNED_FIXTURE"
    tls_identity_verified: Literal[True] = True
    pinned_ips: tuple[str, str]
    duration_ms: int = Field(ge=0, le=30000)

    @model_validator(mode="after")
    def addresses(self) -> Self:
        public_addresses(self.pinned_ips)
        return self


class Snapshot(Frozen):
    evidence_id: UUID
    binding: Binding
    source_kind: Literal["STATIC_HTML_UNVERIFIED"] = "STATIC_HTML_UNVERIFIED"
    provenance: Literal["OWNED_TLS_FIXTURE"] = "OWNED_TLS_FIXTURE"
    observer_version: Literal["cf7-static-observer-lab-v1"] = (
        "cf7-static-observer-lab-v1"
    )
    fetch_policy_version: Literal["owned-get-lab-v1"] = "owned-get-lab-v1"
    snapshot_schema_version: Literal["observation-storage-v1"] = (
        "observation-storage-v1"
    )
    redaction_version: Literal["diagnostic-projection-v1"] = "diagnostic-projection-v1"
    started_at: datetime
    observed_at: datetime
    expires_at: datetime
    decision: Literal["REVIEW_REQUIRED", "BLOCKED", "HUMAN_REQUIRED", "UNSUPPORTED"]
    reason_code: str = Field(max_length=50)
    sales_permission: Literal["UNCERTAIN", "PROHIBITED"]
    captcha_state: Literal["UNVERIFIED", "DETECTED"]
    eligible_for_approval: Literal[False] = False
    execution_allowed: Literal[False] = False
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    robots_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fetch_summary: FetchSummary
    structure_summary: StructureSummary | None

    @model_validator(mode="after")
    def consistency(self) -> Self:
        if self.evidence_id.int == 0:
            raise ValueError("Invalid evidence ID")
        for value in (self.started_at, self.observed_at, self.expires_at):
            if value.utcoffset() != timedelta(0):
                raise ValueError("UTC timestamp required")
        duration = self.observed_at - self.started_at
        if not timedelta(0) <= duration <= timedelta(seconds=30):
            raise ValueError("Invalid observation duration")
        if self.fetch_summary.duration_ms != int(duration.total_seconds() * 1000):
            raise ValueError("Duration mismatch")
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(hours=24):
            raise ValueError("Invalid observation expiry")
        if self.reason_code not in REASONS[self.decision]:
            raise ValueError("Invalid decision reason")
        if self.sales_permission != (
            "PROHIBITED" if self.decision == "BLOCKED" else "UNCERTAIN"
        ):
            raise ValueError("Sales state mismatch")
        if self.captcha_state != (
            "DETECTED" if self.reason_code == "CAPTCHA_DETECTED" else "UNVERIFIED"
        ):
            raise ValueError("CAPTCHA state mismatch")
        if (self.structure_summary is not None) != (self.decision == "REVIEW_REQUIRED"):
            raise ValueError("Structure decision mismatch")
        return self


class Envelope(Frozen):
    snapshot: Snapshot
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def checksum(self) -> Self:
        if digest(canonical(self.snapshot)) != self.snapshot_hash:
            raise ValueError("Snapshot hash mismatch")
        return self


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(snapshot: Snapshot) -> bytes:
    return json.dumps(
        snapshot.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def projected(text: str, limit: int) -> tuple[str, bool, bool]:
    if SENSITIVE.search(text) or any(ord(c) < 32 for c in text):
        return "[REDACTED]", True, False
    return text[:limit], False, len(text) > limit


def projection(observation: observer.Observation) -> StructureSummary | None:
    if observation.structure_json is None:
        return None
    # Input comes from the local parser, never from a public JSON upload.
    data = json.loads(observation.structure_json)
    controls = []
    for position, control in enumerate(data["controls"]):
        name, nr, nt = projected(control["name"], 100)
        label, lr, lt = projected(control["label"], 250)
        controls.append(
            ControlSummary(
                position=position,
                name=name,
                label=label,
                kind=control["kind"],
                required=control["required"],
                default_checked=control["default_checked"],
                redacted=nr or lr,
                truncated=nt or lt,
            )
        )
    return StructureSummary(controls=tuple(controls))


def encode(envelope: Envelope) -> bytes:
    try:
        envelope = Envelope.model_validate(envelope)
    except (ValidationError, ValueError, TypeError):
        raise ContractBlocked("Invalid storage contract") from None
    data = envelope.model_dump_json().encode("utf-8")
    if len(data) > LIMIT:
        raise ContractBlocked("Storage envelope too large")
    return data


def build(
    binding: Binding,
    *,
    evidence_id: UUID,
    body: bytes,
    robots: bytes,
    pinned_ips: tuple[str, str],
    media_type: Literal["text/html", "text/html; charset=utf-8"],
    started_at: datetime,
    observed_at: datetime,
    now: datetime,
    ttl: timedelta = timedelta(hours=24),
) -> Envelope:
    """Trusted internal acquisition metadata only. This is NOT fetch/TLS authorization.

    In the offline lab, supplied receipt fields are synthetic. Future server
    integration must generate these at the actual validated GET boundary.
    """
    if not 0 < len(body) <= 65536 or not 0 < len(robots) <= 16384:
        raise ContractBlocked("Invalid acquisition bounds")
    try:
        result = observer.analyze(
            binding.target_url, body, status=200, media_type=media_type
        )
        snapshot = Snapshot.model_validate(
            {
                "evidence_id": evidence_id,
                "binding": binding,
                "started_at": started_at,
                "observed_at": observed_at,
                "expires_at": observed_at + ttl,
                "decision": result.decision,
                "reason_code": result.reason,
                "sales_permission": result.sales_permission,
                "captcha_state": result.captcha_state,
                "body_sha256": digest(body),
                "parser_evidence_hash": result.evidence_hash,
                "robots_sha256": digest(robots),
                "fetch_summary": FetchSummary(
                    media_type=media_type,
                    body_bytes=len(body),
                    robots_bytes=len(robots),
                    pinned_ips=pinned_ips,
                    duration_ms=int((observed_at - started_at).total_seconds() * 1000),
                ),
                "structure_summary": projection(result),
            }
        )
        envelope = Envelope(
            snapshot=snapshot, snapshot_hash=digest(canonical(snapshot))
        )
        encode(envelope)
        check_current(envelope, binding, now=now)
        return envelope
    except (ValidationError, TransportBlocked, ValueError, TypeError, OverflowError):
        raise ContractBlocked("Invalid storage contract") from None


def check_current(
    envelope: Envelope, expected: Binding, *, now: datetime, retired: bool = False
) -> None:
    """Pure comparison; the future service must read expected/now/retired from DB/server."""
    try:
        envelope = Envelope.model_validate(envelope)
        expected = Binding.model_validate(expected)
    except (ValidationError, ValueError, TypeError):
        raise ContractBlocked("Invalid storage contract") from None
    if now.utcoffset() != timedelta(0):
        raise ContractBlocked("UTC server time required")
    if envelope.snapshot.binding != expected:
        raise ContractBlocked("Current source or execution binding changed")
    if (
        retired
        or not envelope.snapshot.observed_at <= now < envelope.snapshot.expires_at
    ):
        raise ContractBlocked("Observation unavailable or expired")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ContractBlocked("Duplicate storage key")
    return data


def decode(
    data: bytes, expected: Binding, *, now: datetime, retired: bool = False
) -> Envelope:
    """Validate stored bytes, not an external observation ingest endpoint."""
    if not 0 < len(data) <= LIMIT:
        raise ContractBlocked("Storage envelope too large")
    # Bound nesting and nodes BEFORE recursive JSON parsing; strings are skipped.
    depth = nodes = 0
    string = escaped = False
    for char in data:
        if string:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                string = False
        elif char == 34:
            string = True
        elif char in (123, 91):
            depth += 1
            nodes += 1
            if depth > 8 or nodes > 2048:
                raise ContractBlocked("Storage nesting or elements exceeded")
        elif char in (125, 93):
            depth -= 1
        elif char in (44, 58):
            nodes += 1
            if nodes > 2048:
                raise ContractBlocked("Storage elements exceeded")
    try:
        # Reject duplicate keys before Pydantic's JSON parser can normalize them.
        json.loads(data, object_pairs_hook=unique_object)
        envelope = Envelope.model_validate_json(data)
        check_current(envelope, expected, now=now, retired=retired)
        return envelope
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ContractBlocked("Invalid stored envelope") from None
