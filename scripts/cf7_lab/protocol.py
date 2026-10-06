"""Lab-only CF7 observation/classification. No I/O or LeadHive authorization."""

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

HIDDEN = {
    "_wpcf7",
    "_wpcf7_version",
    "_wpcf7_locale",
    "_wpcf7_unit_tag",
    "_wpcf7_container_post",
    "_wpcf7_posted_data_hash",
}
RESPONSE_KEYS = {
    "contact_form_id",
    "status",
    "message",
    "into",
    "invalid_fields",
    "posted_data_hash",
    "demo_mode",
}


def browser_multipart_value(value: str) -> str:
    """Versioned lab encoding rule: browser FormData serializes newlines as CRLF."""
    return re.sub(r"\r\n|\r|\n", "\r\n", value)


@dataclass(frozen=True)
class Observation:
    form_id: int
    unit_tag: str
    endpoint: str
    action: str
    hidden: tuple[tuple[str, str], ...]
    fields: tuple[str, ...]
    fingerprint: str


def observe(html: str, origin: str, index: int = 0) -> Observation:
    # Explicit local lab boundary, not a production URL validator or SSRF exception.
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Only an explicit loopback lab origin is supported")
    if re.search(r"captcha|recaptcha|hcaptcha|turnstile", html, re.IGNORECASE):
        raise ValueError("CAPTCHA requires human handling")
    soup = BeautifulSoup(html, "html.parser")
    configs = []
    for script in soup.find_all("script"):
        matches = re.findall(
            r"\bvar\s+wpcf7\s*=\s*(\{.*?\})\s*;", script.text, re.DOTALL
        )
        configs.extend(json.loads(value) for value in matches)
    if len(configs) != 1:
        raise ValueError("Ambiguous or missing static API configuration")
    api = configs[0]["api"]
    root = api["root"]
    if api["namespace"] != "contact-form-7/v1":
        raise ValueError("Unknown namespace")
    valid_roots = {
        origin + "/wp-json/",
        origin + "/?rest_route=/",
        origin + "/index.php?rest_route=/",
    }
    if root not in valid_roots:
        raise ValueError("Unverified REST root")
    forms = soup.select("form.wpcf7-form")
    form = forms[index]
    if form.get("method", "").lower() != "post":
        raise ValueError("Unknown form method")
    controls = form.select("input[name], textarea[name], select[name]")
    names = [str(field["name"]) for field in controls]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate field names")
    hidden = {
        str(field["name"]): str(field.get("value", ""))
        for field in controls
        if field.get("type") == "hidden"
    }
    if set(hidden) != HIDDEN or hidden["_wpcf7_posted_data_hash"]:
        raise ValueError("Unknown hidden field, token, or previous submission")
    if hidden["_wpcf7_version"] != "6.1.4" or not hidden["_wpcf7"].isdigit():
        raise ValueError("Unverified plugin version or form ID")
    if not re.fullmatch(r"wpcf7-f\d+(?:-p\d+)?-o\d+", hidden["_wpcf7_unit_tag"]):
        raise ValueError("Unverified lab unit tag")
    if not hidden["_wpcf7_unit_tag"].startswith("wpcf7-f" + hidden["_wpcf7"] + "-"):
        raise ValueError("Form ID and unit tag disagree")
    for field in controls:
        if field.name == "select" or field.get("type") in {"file", "password"}:
            raise ValueError("Unsupported control")
    if form.select(
        "[onclick], [onsubmit], [formaction], [formmethod]"
    ) or form.has_attr("onsubmit"):
        raise ValueError("Custom execution path")
    endpoint = (
        root + api["namespace"] + "/contact-forms/" + hidden["_wpcf7"] + "/feedback"
    )
    structure = json.dumps(
        {"form": str(form), "endpoint": endpoint, "api": api},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return Observation(
        int(hidden["_wpcf7"]),
        hidden["_wpcf7_unit_tag"],
        endpoint,
        str(form.get("action", "")),
        tuple(sorted(hidden.items())),
        tuple(name for name in names if name not in hidden),
        hashlib.sha256(structure.encode()).hexdigest(),
    )


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def classify(
    status_code: int, content_type: str, body: bytes, observed: Observation
) -> str:
    """Receipt evidence only. Anything inconclusive remains UNKNOWN; no retries."""
    if (
        status_code != 200
        or content_type.split(";", 1)[0].strip() != "application/json"
    ):
        return "UNKNOWN"
    if len(body) > 64000:
        return "UNKNOWN"
    try:
        result = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        return "UNKNOWN"
    if not isinstance(result, dict) or set(result) - RESPONSE_KEYS:
        return "UNKNOWN"
    if (
        type(result.get("contact_form_id")) is not int
        or result["contact_form_id"] != observed.form_id
        or result.get("into") != "#" + observed.unit_tag
        or result.get("status") != "mail_sent"
        or result.get("invalid_fields") != []
        or not isinstance(result.get("message"), str)
        or not isinstance(result.get("posted_data_hash"), str)
        or not result["posted_data_hash"]
        or ("demo_mode" in result and result["demo_mode"] is not False)
    ):
        return "UNKNOWN"
    return "RECEIPT_REPORTED"
