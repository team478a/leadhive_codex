"""Human operational feedback. Never permission, approval, or global training."""

import ipaddress
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Activity

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


def apply_feedback(company, subject: str, outcome: str, corrected_url: str, reason: str = ""):
    if subject == "company":
        if outcome == "CORRECTED" or corrected_url:
            raise HTTPException(422, "企業の判定にはURL修正を指定できません。")
        if outcome == "NG":
            company.status = "excluded"
        elif outcome == "OK" and reason == "company_verified":
            company.status = "target"
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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_current(event: dict, company) -> bool:
    value = event.get("after_updated_at")
    if not value or not company.updated_at:
        return False
    try:
        return _utc(datetime.fromisoformat(value)) == _utc(company.updated_at)
    except (TypeError, ValueError):
        return False


def latest_company_feedback(db, company):
    rows = db.scalars(
        select(Activity)
        .where(Activity.company_id == company.id, Activity.note.startswith(PREFIX))
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(100)
    ).all()
    for row in rows:
        event = decode(row.note)
        if event and event.get("subject") == "company":
            if is_current(event, company):
                return event
    return None


def latest_company_feedbacks(db, companies):
    if not companies:
        return {}
    company_by_id = {company.id: company for company in companies}
    row_number = func.row_number().over(
        partition_by=Activity.company_id,
        order_by=(Activity.created_at.desc(), Activity.id.desc()),
    )
    recent = (
        select(Activity.company_id, Activity.note, row_number.label("row_number"))
        .where(
            Activity.company_id.in_(company_by_id),
            Activity.note.startswith(PREFIX),
        )
        .subquery()
    )
    rows = db.execute(
        select(recent.c.company_id, recent.c.note, recent.c.row_number)
        .where(recent.c.row_number <= 100)
        .order_by(recent.c.company_id, recent.c.row_number)
    ).all()
    feedback = {}
    for company_id, note, _row_number in rows:
        if company_id in feedback:
            continue
        event = decode(note)
        company = company_by_id[company_id]
        if event and event.get("subject") == "company" and is_current(event, company):
            feedback[company_id] = event
    return feedback


def decode(note: str):
    if not note.startswith(PREFIX):
        return None
    try:
        value = json.loads(note[len(PREFIX) :])
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None
