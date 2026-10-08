"""Target-page GET diagnostics; never grants approval or execution permission."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FormAnalysisLog, FormProfile, User
from app.services.cf7_static_inspection import inspect_isolated, validate_saved
from app.services.form_intelligence.analyzer import _captcha_type
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_intelligence.rules import sales_contact_status
from app.services.form_pinned_get import TargetFetcher
from app.services.scraper import ScrapeError


def source_binding(profile: FormProfile) -> str:
    # Store only a hash: form URLs can contain query tokens.
    payload = [
        str(profile.id),
        profile.form_url,
        profile.action_url,
        profile.form_index,
        profile.fingerprint,
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def latest(db: Session, profile: FormProfile) -> dict | None:
    log = db.scalar(
        select(FormAnalysisLog)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.provider == "rule-target-get",
            FormAnalysisLog.details["operation"].astext == "target_live_check",
        )
        .order_by(FormAnalysisLog.created_at.desc(), FormAnalysisLog.id.desc())
        .limit(1)
    )
    if log is None:
        return None
    data = log.details
    freshness = "INVALID"
    expires_at = None
    try:
        checked_at = datetime.fromisoformat(data["checked_at"])
        if checked_at.tzinfo is not None:
            expires_at = checked_at + timedelta(hours=24)
            if data.get("source_binding") != source_binding(profile):
                freshness = "SOURCE_CHANGED"
            elif checked_at > datetime.now(timezone.utc):
                freshness = "INVALID"
            elif expires_at <= datetime.now(timezone.utc):
                freshness = "EXPIRED"
            else:
                freshness = "CURRENT"
    except (ValueError, KeyError, TypeError):
        pass
    # Explicit whitelist; never expose arbitrary log detail or site content.
    return {
        key: data.get(key)
        for key in (
            "checked_at",
            "saved_fingerprint",
            "observed_fingerprint",
            "structure_status",
            "sales_prohibition_detected",
            "captcha_state",
            "message",
            "fingerprint_match",
            "action_match",
            "method_is_post",
        )
    } | {
        "freshness": freshness,
        "expires_at": expires_at,
        "execution_allowed": False,
        "cf7_static": validate_saved(data.get("cf7_static")),
    }


def check(profile: FormProfile) -> dict:
    result: dict = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "saved_fingerprint": profile.fingerprint,
        "source_binding": source_binding(profile),
        "observed_fingerprint": None,
        "structure_status": "UNVERIFIED",
        "sales_prohibition_detected": False,
        "captcha_state": "UNVERIFIED",
        "execution_allowed": False,
        "message": "",
        "fingerprint_match": None,
        "action_match": None,
        "method_is_post": None,
        "cf7_static": None,
    }
    fetcher = TargetFetcher()
    try:
        page = fetcher.fetch_html(profile.form_url)
        if page.url == profile.form_url:
            result["cf7_static"] = inspect_isolated(page.html, page.url, profile.form_index)
        soup = BeautifulSoup(page.html, "html.parser")
        result["sales_prohibition_detected"] = (
            sales_contact_status(soup.get_text(" ", strip=True), bool(soup.select("form")))[0]
            == "PROHIBITED"
        )
        result["captcha_state"] = (
            "NOT_DETECTED_STATIC" if _captcha_type(page.html) == "CAPTCHA_NONE" else "DETECTED"
        )
        forms = soup.select("form")
        if page.url != profile.form_url:
            result["structure_status"] = "REDIRECTED"
        elif profile.form_index >= len(forms):
            result["structure_status"] = "FORM_NOT_FOUND"
        else:
            form = forms[profile.form_index]
            fingerprint = form_fingerprint(parse_form_fields(form))
            result["observed_fingerprint"] = fingerprint
            action = urljoin(page.url, str(form.get("action") or page.url))

            # A fragment is never sent to the server. Preserve path and query:
            # these identify distinct destinations and must remain significant.
            def without_fragment(value: str) -> str:
                parsed = urlsplit(value)
                return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

            result["fingerprint_match"] = (
                fingerprint == profile.fingerprint if profile.fingerprint else None
            )
            result["action_match"] = (
                without_fragment(action) == without_fragment(profile.action_url)
                if profile.action_url
                else None
            )
            result["method_is_post"] = str(form.get("method") or "get").lower() == "post"
            if not profile.fingerprint or not profile.action_url:
                result["structure_status"] = "SAVED_BASELINE_INCOMPLETE"
            elif not result["method_is_post"]:
                result["structure_status"] = "UNSUPPORTED_METHOD"
            else:
                result["structure_status"] = (
                    "SAME_STRUCTURE"
                    if result["fingerprint_match"]
                    and result["action_match"]
                    and result["method_is_post"]
                    else "CHANGED"
                )
        result["message"] = (
            "静的HTMLの確認結果です。営業許可・CAPTCHAなし・送信承認を保証しません。"
        )
    except ScrapeError as error:
        result["structure_status"] = "FETCH_FAILED"
        result["message"] = error.public_message
    finally:
        fetcher.close()
    return result


def record(db: Session, profile: FormProfile, user: User | None, result: dict) -> None:
    # Keep saved fields, fingerprints and Human corrections intact. Any inability
    # to confirm the saved structure disables its legacy delivery eligibility.
    if result["sales_prohibition_detected"]:
        profile.sales_contact_status = "PROHIBITED"
        profile.form_status = "BLOCKED"
        profile.delivery_supported = False
        profile.review_reason = "現在のページで営業禁止表記を検出しました。"
    elif profile.form_status == "BLOCKED" or profile.sales_contact_status == "PROHIBITED":
        profile.form_status = "BLOCKED"
        profile.delivery_supported = False
    else:
        if result["structure_status"] == "UNSUPPORTED_METHOD":
            profile.form_status = "REVIEW_REQUIRED"
            profile.delivery_supported = False
            profile.review_reason = "通常のPOST送信経路に未対応です。Humanによる確認が必要です。"
        elif result["structure_status"] != "SAME_STRUCTURE":
            profile.form_status = "STALE"
            profile.delivery_supported = False
            profile.review_reason = (
                "現在のフォームと保存済み構造の一致を確認できません。再解析・Human確認が必要です。"
            )
        elif result["captcha_state"] == "DETECTED":
            profile.form_status = "REVIEW_REQUIRED"
            profile.delivery_supported = False
            profile.review_reason = "現在のページでCAPTCHAを検出しました。Human操作が必要です。"
        elif (result.get("cf7_static") or {}).get("status") == "CF7_CANDIDATE":
            profile.form_status = "REVIEW_REQUIRED"
            profile.delivery_supported = False
            profile.review_reason = (
                "CF7の静的構造候補です。実サイト送信対応・Human承認は未完了です。"
            )
        elif (result.get("cf7_static") or {}).get("status") in {"PARSE_FAILED", "LIMIT_EXCEEDED"}:
            profile.form_status = "REVIEW_REQUIRED"
            profile.delivery_supported = False
            profile.review_reason = (
                "限定した構造解析で確認できません。送信せずHuman確認が必要です。"
            )
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            actor_user_id=user.id if user else None,
            event_type="analysis_failed"
            if result["structure_status"] == "FETCH_FAILED"
            else "analysis_completed",
            provider="rule-target-get",
            created_at=datetime.now(timezone.utc),
            details={
                "operation": "target_live_check",
                "principal_type": "HUMAN" if user else "SYSTEM",
                **result,
            },
        )
    )
