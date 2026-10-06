"""Pure CF7 candidate contract. No approval, DB, registry, HTTP or dispatch integration."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import EmailStr, Field, TypeAdapter, model_validator

from app.services.form_execution_plan import FrozenContract, InputValue, PlanError


class Control(FrozenContract):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,99}$")
    kind: Literal["text", "email", "tel", "textarea", "checkbox"]
    required: bool
    label: str = Field(max_length=2000)
    checkbox_value: str = Field(max_length=200)

    @model_validator(mode="after")
    def checkbox(self) -> Control:
        if self.kind == "checkbox":
            if not self.label.strip() or not self.checkbox_value:
                raise ValueError("Explicit checkbox meaning and value required")
        elif self.checkbox_value:
            raise ValueError("Non-checkbox cannot carry checkbox value")
        return self


class Selection(FrozenContract):
    name: str
    checked: bool


def origin(url: str) -> str:
    # Lexical contract only, not DNS safety or an authorization check.
    if not url.isascii() or re.search(r"[\x00-\x20\x7f\\]", url):
        raise ValueError("Invalid URL")
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (
        parts.scheme != "https"
        or parts.netloc != host
        or parts.fragment
        or not re.fullmatch(r"[a-z][a-z0-9.-]{0,252}", host)
        or any(
            not p or len(p) > 63 or p.startswith("-") or p.endswith("-") for p in host.split(".")
        )
        or "." not in host
    ):
        raise ValueError("Canonical HTTPS hostname origin required")
    return "https://" + host


class CF7Candidate(FrozenContract):
    contract_version: Literal["cf7-candidate-v1"] = "cf7-candidate-v1"
    canonicalization_version: Literal["cf7-candidate-json-v1"] = "cf7-candidate-json-v1"
    encoding_version: Literal["browser-crlf-utf8-v1"] = "browser-crlf-utf8-v1"
    environment: Literal["NON_EXECUTABLE"] = "NON_EXECUTABLE"
    delivery_method: Literal["cf7_candidate_only"] = "cf7_candidate_only"
    project_id: UUID
    company_id: UUID
    source_draft_id: UUID
    form_profile_id: UUID
    payload_version: int = Field(ge=1)
    form_url: str = Field(max_length=2000)
    rest_root: str = Field(max_length=2000)
    endpoint: str = Field(max_length=2200)
    method: Literal["POST"] = "POST"
    form_id: int = Field(ge=1, le=2147483647)
    plugin_version: Literal["6.1.4"] = "6.1.4"
    captcha_state: Literal["NONE"]
    execution_path: Literal["STATIC_CF7"] = "STATIC_CF7"
    source_commit: Literal["165278e868387ec393569ecd2dbfda37e8b5b950"] = (
        "165278e868387ec393569ecd2dbfda37e8b5b950"
    )
    dom_fingerprint_version: Literal["cf7-dom-rest-v1"] = "cf7-dom-rest-v1"
    dom_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    hidden: tuple[InputValue, ...] = Field(min_length=6, max_length=6)
    controls: tuple[Control, ...] = Field(min_length=3, max_length=50)
    selections: tuple[Selection, ...] = Field(max_length=20)
    sender: tuple[InputValue, ...] = Field(min_length=4, max_length=4)
    subject: str = Field(max_length=1000)
    body: str = Field(min_length=1, max_length=20000)
    name_field: str
    email_field: str
    body_field: str
    subject_field: str | None = None
    company_field: str | None = None
    phone_field: str | None = None
    field_values: tuple[InputValue, ...] = Field(min_length=3, max_length=50)

    @model_validator(mode="after")
    def binding(self) -> CF7Candidate:
        site = origin(self.form_url)
        roots = {site + "/wp-json/", site + "/?rest_route=/", site + "/index.php?rest_route=/"}
        expected_route = "contact-form-7/v1/contact-forms/" + str(self.form_id) + "/feedback"
        if self.rest_root not in roots or self.endpoint != self.rest_root + expected_route:
            raise ValueError("Exact same-origin CF7 feedback route required")
        for sequence in (
            self.hidden,
            self.controls,
            self.selections,
            self.sender,
            self.field_values,
        ):
            names = [v.name for v in sequence]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate names")
        hidden = {v.name: v for v in self.hidden}
        controls = {v.name: v for v in self.controls}
        selections = {v.name: v for v in self.selections}
        sender = {v.name: v for v in self.sender}
        fields = {v.name: v for v in self.field_values}
        expected_hidden = {
            "_wpcf7",
            "_wpcf7_version",
            "_wpcf7_locale",
            "_wpcf7_unit_tag",
            "_wpcf7_container_post",
            "_wpcf7_posted_data_hash",
        }
        if set(hidden) != expected_hidden or set(sender) != {"name", "email", "company", "phone"}:
            raise ValueError("Known hidden fields and complete sender required")
        h = {v.name: v.value for v in self.hidden}
        if (
            h["_wpcf7"] != str(self.form_id)
            or h["_wpcf7_version"] != self.plugin_version
            or h["_wpcf7_posted_data_hash"]
            or not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", h["_wpcf7_locale"])
            or not re.fullmatch(r"0|[1-9][0-9]*", h["_wpcf7_container_post"])
        ):
            raise ValueError("Hidden identity or previous submission mismatch")
        prefix = "wpcf7-f" + str(self.form_id)
        if h["_wpcf7_container_post"] != "0":
            prefix += "-p" + h["_wpcf7_container_post"]
        if not re.fullmatch(re.escape(prefix) + r"-o[1-9][0-9]*", h["_wpcf7_unit_tag"]):
            raise ValueError("Unit tag mismatch")
        if set(controls) & set(hidden) or set(fields) - set(controls):
            raise ValueError("Unknown or hidden input override")
        sender_values = {v.name: v.value for v in self.sender}
        if (
            not sender_values["name"].strip()
            or str(TypeAdapter(EmailStr).validate_python(sender_values["email"]))
            != sender_values["email"]
        ):
            raise ValueError("Canonical sender identity required")
        bindings = [
            (self.name_field, sender_values["name"], "text"),
            (self.email_field, sender_values["email"], "email"),
            (self.body_field, self.body, "textarea"),
        ]
        if self.subject and self.subject_field is None:
            raise ValueError("Nonempty subject requires explicit field mapping")
        for name, value in [
            (self.subject_field, self.subject),
            (self.company_field, sender_values["company"]),
            (self.phone_field, sender_values["phone"]),
        ]:
            if name is not None:
                bindings.append((name, value, "tel" if name == self.phone_field else "text"))
        if len({v[0] for v in bindings}) != len(bindings):
            raise ValueError("Ambiguous field mapping")
        for name, value, kind in bindings:
            if name not in fields or fields[name].value != value or controls[name].kind != kind:
                raise ValueError("Sender or message mapping mismatch")
        if {v.name for v in self.controls if v.kind == "checkbox"} != set(selections):
            raise ValueError("Every checkbox requires explicit selection")
        for control in self.controls:
            field_value = fields[control.name].value if control.name in fields else None
            if field_value is not None and (
                "\x00" in field_value
                or (control.kind != "textarea" and re.search(r"[\r\n]", field_value))
            ):
                raise ValueError("Unsupported control value transformation")
            if control.kind == "checkbox":
                checked = selections[control.name].checked
                if (checked and field_value != control.checkbox_value) or (
                    not checked and field_value is not None
                ):
                    raise ValueError("Checkbox choice and wire value differ")
                if control.required and not checked:
                    raise ValueError("Required checkbox not selected")
            elif control.required and (field_value is None or not field_value.strip()):
                raise ValueError("Missing required field")
        if sum(len(v.value.encode("utf-8")) for v in (*self.hidden, *self.field_values)) > 40000:
            raise ValueError("Payload too large")
        return self


def canonical(candidate: CF7Candidate) -> dict[str, Any]:
    candidate = CF7Candidate.model_validate(candidate.model_dump(mode="python"))
    # Order is intentionally bound, including controls and multipart fields.
    return candidate.model_dump(mode="json")


def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def wire(candidate: CF7Candidate) -> tuple[str, bytes]:
    data = canonical(candidate)
    boundary = "----LeadHiveCF7" + digest(data)[:32]
    chunks = []
    for value in (*candidate.hidden, *candidate.field_values):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,199}", value.name):
            raise PlanError("Unsafe multipart name")
        encoded = re.sub(r"\r\n|\r|\n", "\r\n", value.value)
        if boundary in encoded:
            raise PlanError("Multipart boundary collision")
        chunks.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{value.name}"'
                f"\r\n\r\n{encoded}\r\n"
            ).encode("utf-8")
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    body = b"".join(chunks)
    if len(body) > 65536:
        raise PlanError("Multipart too large")
    return "multipart/form-data; boundary=" + boundary, body


def snapshot(candidate: CF7Candidate) -> dict[str, Any]:
    data = canonical(candidate)
    content_type, body = wire(candidate)
    return {
        "contract": data,
        "contract_hash": digest(data),
        "content_type": content_type,
        "wire_sha256": hashlib.sha256(body).hexdigest(),
        "wire_size": len(body),
    }


def validate_snapshot(
    saved: dict[str, Any],
    current: CF7Candidate,
    *,
    expected_hash: str,
    expected_version: int,
    project_id: UUID,
    company_id: UUID,
    source_draft_id: UUID,
    form_profile_id: UUID,
) -> None:
    if type(expected_version) is not int or expected_version < 1:
        raise PlanError("Invalid expected version")
    parsed = CF7Candidate.model_validate_json(json.dumps(saved.get("contract")))
    if (
        saved != snapshot(parsed)
        or digest(saved) != expected_hash
        or snapshot(current) != saved
        or parsed.payload_version != expected_version
        or (parsed.project_id, parsed.company_id, parsed.source_draft_id, parsed.form_profile_id)
        != (project_id, company_id, source_draft_id, form_profile_id)
    ):
        raise PlanError("CF7 candidate changed; new preparation and approval required")
