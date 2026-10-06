"""Offline O1 observer proposal. No HTTP, JS execution, DB, approvals or dispatch."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import NoReturn
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

# URL validation only; importing this prototype does not perform DNS or HTTP.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pinned_tls_lab"))
from transport import TransportBlocked, target

VERSION = "cf7-static-observer-lab-v1"
HIDDEN = frozenset(
    {
        "_wpcf7",
        "_wpcf7_version",
        "_wpcf7_locale",
        "_wpcf7_unit_tag",
        "_wpcf7_container_post",
        "_wpcf7_posted_data_hash",
    }
)


@dataclass(frozen=True)
class Observation:
    decision: str
    reason: str
    evidence_hash: str
    source_kind: str = "STATIC_HTML_UNVERIFIED"
    sales_permission: str = "UNCERTAIN"
    captcha_state: str = "UNVERIFIED"
    eligible_for_approval: bool = field(default=False, init=False)
    structure_json: str | None = None


class AmbiguousHTML(ValueError):
    pass


class AttributeGuard(HTMLParser):
    """Reject ambiguity before BeautifulSoup repairs duplicate attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.count += 1
        names = [name for name, _ in attrs]
        if self.count > 10000 or len(names) != len(set(names)):
            raise AmbiguousHTML("ambiguous attributes or tag limit")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("duplicate config keys")
    return values


def reject_constant(value: str) -> NoReturn:
    raise ValueError("non-JSON config constant")


def origin(url: str) -> tuple[str, int]:
    return target(url), urlsplit(url).port or 443


def classes(tag: Tag) -> set[str]:
    value = tag.get("class")
    if isinstance(value, list):
        return {str(item) for item in value}
    return set(value.split()) if isinstance(value, str) else set()


def analyze(
    page_url: str,
    body: bytes,
    *,
    status: int = 200,
    media_type: str = "text/html; charset=utf-8",
) -> Observation:
    """Supplied bytes only. Results are observations, never execution authority."""
    checksum = hashlib.sha256(body if len(body) <= 65536 else b"").hexdigest()

    def outcome(
        decision: str, reason: str, structure: dict[str, object] | None = None
    ) -> Observation:
        encoded = (
            json.dumps(
                structure, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if structure is not None
            else None
        )
        evidence = json.dumps(
            [
                VERSION,
                page_url,
                status,
                media_type,
                checksum,
                decision,
                reason,
                encoded,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return Observation(
            decision,
            reason,
            hashlib.sha256(evidence.encode()).hexdigest(),
            sales_permission="PROHIBITED"
            if reason == "SALES_PROHIBITED"
            else "UNCERTAIN",
            captcha_state="DETECTED" if reason == "CAPTCHA_DETECTED" else "UNVERIFIED",
            structure_json=encoded,
        )

    try:
        page_origin = origin(page_url)
        if urlsplit(page_url).query or "%" in urlsplit(page_url).path:
            return outcome("UNSUPPORTED", "PAGE_URL_POLICY")
    except (TransportBlocked, ValueError):
        return outcome("UNSUPPORTED", "PAGE_URL_POLICY")
    if status != 200 or media_type.lower() not in {
        "text/html",
        "text/html; charset=utf-8",
    }:
        return outcome("UNSUPPORTED", "HTTP_METADATA")
    if not 0 < len(body) <= 65536 or b"\x00" in body:
        return outcome("UNSUPPORTED", "BODY_BOUNDS")
    try:
        html = body.decode("utf-8", errors="strict")
        AttributeGuard().feed(html)
    except (UnicodeDecodeError, AmbiguousHTML):
        return outcome("UNSUPPORTED", "HTML_ENCODING_OR_ATTRIBUTES")
    soup = BeautifulSoup(html, "html.parser")
    if any(
        str(tag.get("charset", "utf-8")).lower() not in {"utf-8", "utf8"}
        for tag in soup.select("meta[charset]")
    ):
        return outcome("UNSUPPORTED", "HTML_CHARSET")
    visible = BeautifulSoup(html, "html.parser")
    for tag in visible.select("script, style"):
        tag.decompose()
    text = re.sub(r"\s+", "", visible.get_text()).lower()
    if any(
        word in text
        for word in (
            "営業禁止",
            "営業目的のお問い合わせはお断り",
            "営業メールお断り",
            "nosolicitation",
        )
    ):
        return outcome("BLOCKED", "SALES_PROHIBITED")
    if re.search(r"captcha|recaptcha|hcaptcha|turnstile", html, re.IGNORECASE):
        return outcome("HUMAN_REQUIRED", "CAPTCHA_DETECTED")
    if soup.find("base"):
        return outcome("HUMAN_REQUIRED", "BASE_URL_OVERRIDE")
    ids = [str(tag["id"]) for tag in soup.select("[id]")]
    if len(ids) != len(set(ids)):
        return outcome("UNSUPPORTED", "DUPLICATE_IDS")
    forms = soup.find_all("form")
    if len(forms) != 1 or "wpcf7-form" not in classes(forms[0]):
        return outcome("UNSUPPORTED", "FORM_COUNT_OR_TYPE")
    form = forms[0]
    if str(form.get("method", "")).lower() != "post":
        return outcome("UNSUPPORTED", "FORM_METHOD")
    if any(
        any(
            str(key).lower().startswith("on") or key in {"formaction", "formmethod"}
            for key in tag.attrs
        )
        for tag in [form, *form.find_all()]
    ):
        return outcome("HUMAN_REQUIRED", "CUSTOM_EXECUTION")
    if form.select("script, iframe"):
        return outcome("HUMAN_REQUIRED", "CUSTOM_EXECUTION")
    configs = []
    try:
        for script in soup.find_all("script"):
            source = script.get_text()
            if not re.search(r"\b(?:var|let|const)\s+wpcf7\s*=", source):
                continue
            match = re.fullmatch(
                r"\s*(?:var|let|const)\s+wpcf7\s*=\s*(\{.*\})\s*;?\s*",
                source,
                re.DOTALL,
            )
            if not match:
                raise ValueError("dynamic config")
            configs.append(
                json.loads(
                    match[1],
                    object_pairs_hook=unique_object,
                    parse_constant=reject_constant,
                )
            )
        if len(configs) != 1:
            raise ValueError("ambiguous config")
        api = configs[0]["api"]
        root = api["root"]
        if api["namespace"] != "contact-form-7/v1" or origin(root) != page_origin:
            raise ValueError("route origin")
        parts = urlsplit(root)
        if (
            parts.query
            or not parts.path.endswith("/wp-json/")
            or "%" in parts.path
            or ".." in parts.path
        ):
            raise ValueError("route shape")
    except (ValueError, TypeError, KeyError, TransportBlocked):
        return outcome("UNSUPPORTED", "STATIC_CONFIG_OR_ROOT")
    fields = form.select("input, textarea, select, button")
    if any(
        not tag.has_attr("name")
        and not (
            tag.get("type") == "submit"
            or tag.name == "button"
            and tag.get("type", "submit") == "submit"
        )
        for tag in fields
    ):
        return outcome("UNSUPPORTED", "UNNAMED_CONTROL")
    named = [tag for tag in fields if tag.has_attr("name")]
    if any(
        not isinstance(tag.get("name"), str) or not tag.get("name") for tag in named
    ):
        return outcome("UNSUPPORTED", "FIELD_NAMES_OR_LIMIT")
    names = [str(tag["name"]) for tag in named]
    if len(names) != len(set(names)) or len(named) > 56:
        return outcome("UNSUPPORTED", "FIELD_NAMES_OR_LIMIT")
    if any(tag.get("form") for tag in soup.select("[form]")):
        return outcome("HUMAN_REQUIRED", "EXTERNAL_FORM_CONTROLS")
    hidden = {
        str(tag["name"]): str(tag.get("value", ""))
        for tag in named
        if tag.get("type") == "hidden"
    }
    if set(hidden) != HIDDEN or hidden["_wpcf7_posted_data_hash"]:
        return outcome("UNSUPPORTED", "HIDDEN_OR_TOKEN")
    number, post = hidden["_wpcf7"], hidden["_wpcf7_container_post"]
    unit = hidden["_wpcf7_unit_tag"]
    if (
        hidden["_wpcf7_version"] != "6.1.4"
        or not re.fullmatch(r"[1-9][0-9]{0,9}", number)
        or not re.fullmatch(r"[0-9]{1,10}", post)
        or not re.fullmatch(rf"wpcf7-f{number}-p{post}-o[1-9][0-9]*", unit)
        or not re.fullmatch(r"[a-zA-Z]{2,3}_[a-zA-Z]{2}", hidden["_wpcf7_locale"])
    ):
        return outcome("UNSUPPORTED", "VERSION_OR_ID_BINDING")
    action = urljoin(page_url, str(form.get("action", "")))
    try:
        parsed_action = urlsplit(action)
        if (
            parsed_action.fragment not in ("", unit)
            or parsed_action.query
            or "%" in parsed_action.path
            or origin(action.split("#", 1)[0]) != page_origin
        ):
            raise ValueError("action binding")
    except (ValueError, TransportBlocked):
        return outcome("HUMAN_REQUIRED", "FORM_ACTION")
    controls = []
    for tag in named:
        name = str(tag["name"])
        if name in hidden:
            continue
        kind = (
            "textarea"
            if tag.name == "textarea"
            else str(tag.get("type", "text")).lower()
        )
        if (
            tag.name not in {"input", "textarea"}
            or kind not in {"text", "email", "tel", "textarea", "checkbox"}
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,99}", name)
        ):
            return outcome("UNSUPPORTED", "CONTROL_TYPE_OR_NAME")
        if tag.has_attr("disabled") or tag.has_attr("readonly"):
            return outcome("HUMAN_REQUIRED", "CONTROL_STATE")
        label = tag.find_parent("label")
        if label is None and tag.get("id"):
            labels = soup.find_all("label", attrs={"for": tag["id"]})
            if len(labels) == 1:
                label = labels[0]
        if label is None or not label.get_text(" ", strip=True):
            return outcome("HUMAN_REQUIRED", "LABEL_UNVERIFIED")
        required = tag.has_attr("required") or tag.get("aria-required") == "true"
        if kind == "checkbox":
            acceptance = tag.find_parent(class_="wpcf7-acceptance")
            if acceptance is None or "invert" in classes(acceptance):
                return outcome("HUMAN_REQUIRED", "ACCEPTANCE_UNSUPPORTED")
            required = "optional" not in classes(acceptance)
            if not tag.get("value"):
                return outcome("UNSUPPORTED", "CHECKBOX_VALUE")
        controls.append(
            {
                "name": name,
                "kind": kind,
                "label": label.get_text(" ", strip=True),
                "required": required,
                "checkbox_value": str(tag.get("value", ""))
                if kind == "checkbox"
                else "",
                "default_checked": tag.has_attr("checked"),
            }
        )
    if len(controls) < 3:
        return outcome("UNSUPPORTED", "CONTROL_COUNT")
    return outcome(
        "REVIEW_REQUIRED",
        "STATIC_ONLY_UNVERIFIED",
        {
            "form_url": page_url,
            "declared_action": action,
            "rest_root": root,
            "endpoint": root
            + "contact-form-7/v1/contact-forms/"
            + number
            + "/feedback",
            "hidden": hidden,
            "controls": controls,
            "html_sha256": checksum,
            "mapping": "HUMAN_REQUIRED",
        },
    )
