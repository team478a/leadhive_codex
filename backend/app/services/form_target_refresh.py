"""Conservative single-page reanalysis. No AI, discovery, approval or dispatch."""

from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, FormAnalysisLog, FormProfile, FormProfileField, User
from app.services.form_intelligence.analyzer import (
    ANALYSIS_VERSION,
    _captcha_type,
    _confirmation_page,
    _upsert_profile,
)
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_intelligence.rules import sales_contact_status
from app.services.form_live_check import TargetFetcher, record, source_binding
from app.services.scraper import ScrapeError


def refresh(db: Session, profile: FormProfile, user: User | None) -> dict:
    db.scalar(
        select(FormProfile)
        .where(FormProfile.id == profile.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    stored = list(
        db.scalars(
            select(FormProfileField)
            .where(FormProfileField.form_profile_id == profile.id)
            .with_for_update()
        ).all()
    )
    fetcher = TargetFetcher()
    try:
        page = fetcher.fetch_html(profile.form_url)
    except ScrapeError as exc:
        raise HTTPException(422, exc.public_message) from None
    finally:
        fetcher.close()
    if page.url != profile.form_url:
        raise HTTPException(409, "ページが移動しました。元の対象を確認してください。")
    soup = BeautifulSoup(page.html, "html.parser")
    forms = soup.select("form")
    if profile.form_index >= len(forms):
        raise HTTPException(409, "保存された位置にフォームがありません。対象を確認してください。")
    form = forms[profile.form_index]
    fields = parse_form_fields(form)
    fingerprint = form_fingerprint(fields)
    action = urlsplit(urljoin(page.url, str(form.get("action") or page.url)))
    action_url = urlunsplit((action.scheme, action.netloc, action.path, action.query, ""))
    same_fields = bool(profile.fingerprint) and fingerprint == profile.fingerprint
    manual = any(field.decision_source == "MANUAL" for field in stored)
    prohibited = (
        profile.form_status == "BLOCKED"
        or profile.sales_contact_status == "PROHIBITED"
        or sales_contact_status(soup.get_text(" ", strip=True), True)[0] == "PROHIBITED"
    )
    before_hash = profile.fingerprint
    if manual and (not same_fields or action_url != profile.action_url):
        profile.form_status = "BLOCKED" if prohibited else "STALE"
        if prohibited:
            profile.sales_contact_status = "PROHIBITED"
        profile.delivery_supported = False
        profile.review_reason = (
            "手動確認済み情報と現在のフォームが一致しません。上書きせずHuman確認が必要です。"
        )
        result = dict(
            profile_id=str(profile.id),
            refresh_applied=False,
            message=profile.review_reason,
            form_status=profile.form_status,
            preserved_field_ids=True,
            protected_manual_values=True,
            execution_allowed=False,
            human_approved=False,
        )
        _log(db, profile, user, result, before_hash)
        return result
    captcha = _captcha_type(page.html)
    if captcha == "CAPTCHA_NONE" and profile.captcha_type != "CAPTCHA_NONE":
        captcha = profile.captcha_type
    if not same_fields:
        company = db.get(Company, profile.company_id)
        assert company is not None
        profile = _upsert_profile(
            db,
            company,
            profile.form_url,
            profile.form_index,
            form_found=True,
            page_kind=profile.page_kind,
            fields=fields,
            sales_status="PROHIBITED" if prohibited else "UNCERTAIN",
            captcha=captcha,
            confirmation=_confirmation_page(form),
            duration_ms=0,
            provider_name="rule-target-refresh",
            delivery_supported=False,
            action_url=action_url,
        )
    profile.fingerprint = fingerprint
    profile.action_url = action_url
    profile.form_found = True
    profile.sales_contact_status = "PROHIBITED" if prohibited else "UNCERTAIN"
    profile.captcha_type = captcha
    profile.confirmation_page = _confirmation_page(form)
    profile.form_status = "BLOCKED" if prohibited else "REVIEW_REQUIRED"
    profile.delivery_supported = False
    profile.analysis_version = ANALYSIS_VERSION
    profile.analysis_provider = "rule-target-refresh"
    profile.last_analyzed_at = datetime.now(timezone.utc)
    profile.error_message = ""
    profile.review_reason = (
        "対象ページを再解析しました。用途・選択・同意・送信経路のHuman確認が必要です。"
    )
    result = dict(
        profile_id=str(profile.id),
        refresh_applied=True,
        field_count=len(fields),
        preserved_field_ids=same_fields,
        protected_manual_values=manual,
        form_status=profile.form_status,
        execution_allowed=False,
        human_approved=False,
        fingerprint=fingerprint,
    )
    _log(db, profile, user, result, before_hash)
    record(
        db,
        profile,
        user,
        dict(
            checked_at=datetime.now(timezone.utc).isoformat(),
            source_binding=source_binding(profile),
            saved_fingerprint=profile.fingerprint,
            observed_fingerprint=fingerprint,
            fingerprint_match=True,
            action_match=True,
            method_is_post=str(form.get("method") or "get").lower() == "post",
            structure_status="SAME_STRUCTURE"
            if str(form.get("method") or "get").lower() == "post"
            else "UNSUPPORTED_METHOD",
            sales_prohibition_detected=sales_contact_status(soup.get_text(" ", strip=True), True)[0]
            == "PROHIBITED",
            captcha_state="NOT_DETECTED_STATIC"
            if _captcha_type(page.html) == "CAPTCHA_NONE"
            else "DETECTED",
            execution_allowed=False,
            message="対象ページの再解析時の観測です。営業許可・送信承認ではありません。",
        ),
    )
    result["form_status"] = profile.form_status
    return result


def _log(
    db: Session, profile: FormProfile, user: User | None, result: dict, before_hash: str
) -> None:
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            actor_user_id=user.id if user else None,
            event_type="analysis_completed",
            provider="rule-target-refresh",
            created_at=datetime.now(timezone.utc),
            details={
                "operation": "target_form_refresh",
                "principal_type": "HUMAN" if user else "SYSTEM",
                "before_fingerprint": before_hash,
                **result,
            },
        )
    )
