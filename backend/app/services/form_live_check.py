"""Target-page GET diagnostics; never grants approval or execution permission."""

from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models import FormAnalysisLog, FormProfile, User
from app.services.form_intelligence.analyzer import _captcha_type
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_intelligence.rules import sales_contact_status
from app.services.scraper import SafeFetcher, ScrapeError


class TargetFetcher(SafeFetcher):
    def _request(self, url, max_bytes, redirects=0, robots_request=False):
        # The base fetcher validates every destination. Check robots on redirected
        # HTML destinations too, without adding links or common-path discovery.
        if not robots_request and not self.robots_allowed(url):
            raise ScrapeError("robots.txtにより解析が許可されていません。")
        return super()._request(url, max_bytes, redirects, robots_request)


def check(profile: FormProfile) -> dict:
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "saved_fingerprint": profile.fingerprint,
        "observed_fingerprint": None,
        "structure_status": "UNVERIFIED",
        "sales_prohibition_detected": False,
        "captcha_state": "UNVERIFIED",
        "execution_allowed": False,
        "message": "",
    }
    fetcher = TargetFetcher()
    try:
        page = fetcher.fetch_html(profile.form_url)
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
            result["structure_status"] = (
                "SAME_STRUCTURE"
                if profile.fingerprint
                and fingerprint == profile.fingerprint
                and action == profile.action_url
                and str(form.get("method") or "get").lower() == "post"
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


def record(db: Session, profile: FormProfile, user: User, result: dict) -> None:
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
        if result["structure_status"] != "SAME_STRUCTURE":
            profile.form_status = "STALE"
            profile.delivery_supported = False
            profile.review_reason = (
                "現在のフォームと保存済み構造の一致を確認できません。再解析・Human確認が必要です。"
            )
        elif result["captcha_state"] == "DETECTED":
            profile.form_status = "REVIEW_REQUIRED"
            profile.delivery_supported = False
            profile.review_reason = "現在のページでCAPTCHAを検出しました。Human操作が必要です。"
    db.add(
        FormAnalysisLog(
            company_id=profile.company_id,
            form_profile_id=profile.id,
            actor_user_id=user.id,
            event_type="analysis_failed"
            if result["structure_status"] == "FETCH_FAILED"
            else "analysis_completed",
            provider="rule-target-get",
            details={"operation": "target_live_check", **result},
        )
    )
