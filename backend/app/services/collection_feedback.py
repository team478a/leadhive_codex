"""Human operational feedback. Never permission, approval, or global training."""

import ipaddress
import json
from urllib.parse import urlsplit

from fastapi import HTTPException

PREFIX = "[collection-feedback-v1] "


def correction_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
            or "." not in host
            or host.lower().endswith((".localhost", ".local", ".internal"))
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "公開ページのHTTP/HTTPS URLを入力してください。") from None
    return value


def apply_feedback(company, subject: str, outcome: str, corrected_url: str):
    if subject == "company":
        if outcome == "CORRECTED" or corrected_url:
            raise HTTPException(422, "企業の判定にはURL修正を指定できません。")
        if outcome == "NG":
            company.status = "excluded"
        return
    if outcome == "OK" and not company.contact_url:
        raise HTTPException(422, "問い合わせURLが未検出です。正しいURLを入力してください。")
    if outcome == "OK":
        correction_url(company.contact_url)
    if outcome == "CORRECTED":
        company.contact_url = correction_url(corrected_url)
    elif corrected_url:
        raise HTTPException(422, "URL修正を選択してください。")
    elif outcome == "NG":
        company.contact_url = ""
    company.protected_fields = list(
        dict.fromkeys([*(company.protected_fields or []), "contact_url"])
    )


def decode(note: str):
    if not note.startswith(PREFIX):
        return None
    try:
        value = json.loads(note[len(PREFIX) :])
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None
