"""Hostname-based spacing, shared by all projects using this execution environment."""

from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import ApprovedFormDispatch, FormDispatchLimits, FormDispatchSite
from app.services import human_approval as approval


def site_keys(form_url, action_url):
    keys = set()
    for url in (form_url, action_url):
        try:
            parsed = urlsplit(url or "")
            host = (parsed.hostname or "").rstrip(".").lower().encode("idna").decode("ascii")
            if host.startswith("www."):
                host = host[4:]
            if parsed.scheme not in {"http", "https"} or not host or len(host) > 253:
                raise ValueError()
            keys.add(host)
        except (ValueError, UnicodeError):
            raise HTTPException(409, "フォームのサイト識別情報を確認できません。") from None
    return sorted(keys)


def active_sites(db):
    limits = db.get(FormDispatchLimits, 1, populate_existing=True)
    if not limits:
        raise HTTPException(409, "送信上限設定を確認できません。")
    return (
        select(FormDispatchSite.site_key)
        .join(ApprovedFormDispatch, ApprovedFormDispatch.id == FormDispatchSite.dispatch_id)
        .where(
            ApprovedFormDispatch.started_at
            > approval.now() - timedelta(seconds=limits.site_interval_seconds)
        )
    )


def eligible(db, row):
    expected = site_keys(row.form_url, row.payload_snapshot.get("form_action_url"))
    stored = sorted(
        db.scalars(
            select(FormDispatchSite.site_key).where(FormDispatchSite.dispatch_id == row.id)
        ).all()
    )
    if expected != stored:
        raise HTTPException(409, "固定したサイト識別情報が一致しません。")
    return (
        db.scalar(active_sites(db).where(FormDispatchSite.site_key.in_(expected)).limit(1)) is None
    )


def wait_times(db, rows):
    limits = db.get(FormDispatchLimits, 1)
    if not limits or not rows:
        return {}
    links = db.execute(
        select(FormDispatchSite.dispatch_id, FormDispatchSite.site_key).where(
            FormDispatchSite.dispatch_id.in_([row.id for row in rows])
        )
    ).all()
    keys = {link.site_key for link in links}
    latest = dict(
        db.execute(
            select(FormDispatchSite.site_key, func.max(ApprovedFormDispatch.started_at))
            .join(ApprovedFormDispatch, ApprovedFormDispatch.id == FormDispatchSite.dispatch_id)
            .where(
                FormDispatchSite.site_key.in_(keys),
                ApprovedFormDispatch.started_at
                > approval.now() - timedelta(seconds=limits.site_interval_seconds),
            )
            .group_by(FormDispatchSite.site_key)
        ).all()
    )
    result = {}
    for link in links:
        if link.site_key in latest:
            until = latest[link.site_key] + timedelta(seconds=limits.site_interval_seconds)
            result[link.dispatch_id] = max(result.get(link.dispatch_id, until), until)
    return result
