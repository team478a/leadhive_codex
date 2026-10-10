import logging
import re
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Company, FormAnalysisLog, FormProfile, FormProfileField, Project
from app.services.contact_discovery import (
    contact_pages,
    embedded_form_providers,
    external_contact_links,
    is_contact_form,
    same_site,
)
from app.services.form_intelligence.compatibility import assess_delivery_compatibility
from app.services.form_intelligence.fields import mapping_review_reason, parse_form_fields
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_intelligence.providers import (
    AmbiguousField,
    DecisionContext,
    FormDecisionError,
    get_form_decision_provider,
)
from app.services.form_intelligence.rules import (
    recommended_option,
    sales_contact_status,
)
from app.services.scraper import CONTACT_HINTS, SafeFetcher, ScrapeError

logger = logging.getLogger("leadhive")
ANALYSIS_VERSION = "2.0"
MAX_CONTACT_PAGES = 8
MAX_EXTERNAL_CONTACT_PAGES = 3
COMMON_CONTACT_PATHS = ("/contact", "/contact-us", "/inquiry", "/inquiry-form")


def _same_origin(left: str, right: str) -> bool:
    a, b = urlsplit(left), urlsplit(right)
    return a.scheme == b.scheme and (a.hostname or "").removeprefix("www.") == (
        b.hostname or ""
    ).removeprefix("www.")


def _clean_url(value: str, base_url: str) -> str:
    parsed = urlsplit(urljoin(base_url, value.strip()))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _page_kind(url: str, text: str) -> str:
    value = f"{url} {text[:2000]}".lower()
    if any(item in value for item in ("recruit", "career", "採用", "求人")):
        return "recruitment"
    if any(item in value for item in ("support", "サポート", "不具合")):
        return "support"
    if any(item in value for item in ("partner", "alliance", "提携", "協業", "法人")):
        return "partnership"
    if any(item in value for item in ("document", "download", "資料請求")):
        return "document_request"
    return "general"


def _candidate_pages(company: Company, root_url: str, root_html: str) -> list[tuple[str, bool]]:
    soup = BeautifulSoup(root_html, "html.parser")
    candidates: list[tuple[str, bool]] = []

    def add(url: str, explicit: bool) -> None:
        clean = _clean_url(url, root_url)
        if not clean or not _same_origin(clean, root_url):
            return
        if clean not in {item[0] for item in candidates}:
            candidates.append((clean, explicit))

    if soup.select_one("form"):
        add(root_url, True)
    if company.contact_url:
        add(company.contact_url, True)
    for anchor in soup.select("a[href]"):
        label = anchor.get_text(" ", strip=True).lower()
        href = str(anchor.get("href") or "")
        combined = f"{label} {href.lower()}"
        if any(hint.lower() in combined for hint in CONTACT_HINTS):
            add(href, True)
    parsed = urlsplit(root_url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    for path in COMMON_CONTACT_PATHS:
        add(origin + path, False)
    return candidates[:MAX_CONTACT_PAGES]


def _captcha_type(html: str) -> str:
    value = html.lower()
    if "hcaptcha" in value or "h-captcha" in value:
        return "CAPTCHA_HCAPTCHA"
    if "turnstile" in value or "cf-turnstile" in value:
        return "CAPTCHA_TURNSTILE"
    if "recaptcha" in value or "g-recaptcha" in value:
        return "CAPTCHA_RECAPTCHA"
    if "captcha" in value or "画像認証" in value or "認証コード" in value:
        return "CAPTCHA_OTHER"
    return "CAPTCHA_NONE"


def _confirmation_page(form: Tag) -> bool | None:
    buttons = " ".join(
        [
            item.get_text(" ", strip=True) or str(item.get("value") or "")
            for item in form.select("button, input[type='submit']")
        ]
    )
    if re.search(r"確認|confirm", buttons, re.IGNORECASE):
        return True
    if re.search(r"送信|submit|send", buttons, re.IGNORECASE):
        return False
    return None


def _profile_status(
    form_found: bool,
    sales_status: str,
    captcha: str,
    confirmation: bool | None,
    fields: list[dict],
    delivery_supported: bool,
) -> str:
    if sales_status == "PROHIBITED":
        return "BLOCKED"
    if (
        not form_found
        or sales_status == "UNCERTAIN"
        or captcha != "CAPTCHA_NONE"
        or not delivery_supported
    ):
        return "REVIEW_REQUIRED"
    if confirmation is None or mapping_review_reason(fields):
        return "REVIEW_REQUIRED"
    return "READY"


def _review_reason(
    form_found: bool,
    sales_status: str,
    captcha: str,
    confirmation: bool | None,
    fields: list[dict],
    compatibility_reason: str,
) -> str:
    if sales_status == "PROHIBITED":
        return "営業禁止を検出しました。送信対象から除外します。"
    if not form_found:
        return "送信可能なフォームが見つかりません。"
    if sales_status == "UNCERTAIN":
        return "営業目的で利用できるか確認が必要です。"
    if captcha != "CAPTCHA_NONE":
        return "CAPTCHAは人による操作・確認が必要です。自動送信できません。"
    if compatibility_reason:
        return compatibility_reason
    if confirmation is None:
        return "送信ボタンを判定できないため確認が必要です。"
    return mapping_review_reason(fields)


def _log(
    db: Session,
    company_id,
    event_type: str,
    *,
    profile_id=None,
    provider: str = "",
    duration_ms: int = 0,
    usage: dict | None = None,
    estimated_cost: float | None = None,
    confidence: float | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        FormAnalysisLog(
            company_id=company_id,
            form_profile_id=profile_id,
            event_type=event_type,
            provider=provider,
            duration_ms=max(0, duration_ms),
            usage=usage or {},
            estimated_cost=estimated_cost,
            confidence=confidence,
            details=details or {},
        )
    )


def _upsert_profile(
    db: Session,
    company: Company,
    url: str,
    form_index: int,
    *,
    form_found: bool,
    page_kind: str,
    fields: list[dict],
    sales_status: str,
    captcha: str,
    confirmation: bool | None,
    duration_ms: int,
    provider_name: str,
    delivery_supported: bool = False,
    compatibility_reason: str = "",
    error_message: str = "",
    action_url: str = "",
) -> FormProfile:
    profile = db.scalar(
        select(FormProfile).where(
            FormProfile.company_id == company.id,
            FormProfile.form_url == url,
            FormProfile.form_index == form_index,
        )
    )
    previous_fingerprint = profile.fingerprint if profile else ""
    if profile is None:
        profile = FormProfile(company_id=company.id, form_url=url, form_index=form_index)
        db.add(profile)
        db.flush()
    manual = {
        (item.name, item.selector): (item.mapped_key, item.recommended_value)
        for item in db.scalars(
            select(FormProfileField).where(
                FormProfileField.form_profile_id == profile.id,
                FormProfileField.decision_source == "MANUAL",
            )
        ).all()
    }
    for item in fields:
        manual_value = manual.get((item["name"], item["selector"]))
        if manual_value:
            item["mapped_key"], item["recommended_value"] = manual_value
            item["confidence"], item["decision_source"] = 1.0, "MANUAL"
    fingerprint = form_fingerprint(fields) if fields else ""
    status = (
        "ERROR"
        if error_message
        else _profile_status(
            form_found,
            sales_status,
            captcha,
            confirmation,
            fields,
            delivery_supported,
        )
    )
    if (
        status != "BLOCKED"
        and previous_fingerprint
        and fingerprint
        and previous_fingerprint != fingerprint
    ):
        status = "STALE"
    profile.form_status = status
    profile.sales_contact_status = sales_status
    profile.captcha_type = captcha
    profile.confirmation_page = confirmation
    profile.form_found = form_found
    profile.page_kind = page_kind
    profile.fingerprint = fingerprint
    profile.action_url = action_url
    profile.analysis_version = ANALYSIS_VERSION
    profile.analysis_provider = provider_name
    profile.last_analyzed_at = datetime.now(timezone.utc)
    profile.analysis_duration_ms = max(0, duration_ms)
    profile.delivery_supported = delivery_supported
    profile.review_reason = (
        _review_reason(
            form_found,
            sales_status,
            captcha,
            confirmation,
            fields,
            compatibility_reason,
        )[:500]
        if status in {"REVIEW_REQUIRED", "BLOCKED"}
        else ""
    )
    profile.error_message = error_message[:500]
    db.execute(delete(FormProfileField).where(FormProfileField.form_profile_id == profile.id))
    for item in fields:
        db.add(
            FormProfileField(
                form_profile_id=profile.id,
                **{key: value for key, value in item.items() if key != "element_id"},
            )
        )
    return profile


def analyze_company_forms(
    db: Session, company: Company, force: bool = False, *, allow_ai: bool = True
) -> list[FormProfile]:
    # A requested analysis always refreshes the snapshot; force is kept for the job contract.
    del force
    started = time.monotonic()
    _log(db, company.id, "analysis_started", details={"analysis_version": ANALYSIS_VERSION})
    if not company.website_url:
        profile = _upsert_profile(
            db,
            company,
            company.contact_url or "about:blank",
            0,
            form_found=False,
            page_kind="general",
            fields=[],
            sales_status="UNCERTAIN",
            captcha="CAPTCHA_NONE",
            confirmation=None,
            duration_ms=0,
            provider_name="rule",
            error_message="WebサイトURLが登録されていません。",
        )
        _log(
            db,
            company.id,
            "analysis_failed",
            profile_id=profile.id,
            details={"reason": profile.error_message},
        )
        db.commit()
        return [profile]

    project = db.get(Project, company.project_id)
    fetcher = SafeFetcher()
    seen: set[tuple[str, int]] = set()
    profiles: list[FormProfile] = []
    prohibitions: list[tuple[str, str]] = []
    try:
        root = fetcher.fetch_html(company.website_url)
        fetcher.site_root = root.url
        root_cache = {root.url: root.html}
        external_seen: set[str] = set()
        external_candidates: list[str] = []
        root_permission, root_prohibition = sales_contact_status(
            BeautifulSoup(root.html, "html.parser").get_text(" ", strip=True), False
        )

        def record_prohibition(matched: str, source_url: str) -> None:
            if not matched:
                return
            if (matched, source_url) not in prohibitions:
                prohibitions.append((matched, source_url))
            # Sticky exclusion, shared by existing email/form guards. A later
            # successful fetch must never silently restore contact permission.
            company.do_not_contact = True
            if not (company.exclusion_reason or "").startswith("営業NG："):
                company.exclusion_reason = (
                    f"営業NG：{matched} / {company.exclusion_reason or ''}"
                )[:500]
            _log(
                db,
                company.id,
                "sales_prohibition_detected",
                details={"matched_text": matched, "url": source_url},
            )

        record_prohibition(root_prohibition, root.url)

        def record_external_links(html: str, source_url: str) -> None:
            for candidate in external_contact_links(html, source_url, root.url):
                if candidate["url"] in external_seen or len(external_seen) >= 8:
                    continue
                external_seen.add(candidate["url"])
                external_candidates.append(candidate["url"])
                _log(
                    db,
                    company.id,
                    "contact_page_found",
                    details={
                        **candidate,
                        "finding": "EXTERNAL_CONTACT_UNVERIFIED",
                        "discovery_method": "OFFICIAL_SITE_LINK",
                    },
                )

        record_external_links(root.html, root.url)
        resolved_urls: dict[str, str] = {}
        local_pages = contact_pages(
            root.url,
            root_cache,
            company.contact_url or "",
            max_pages=MAX_CONTACT_PAGES,
            resolved_urls=resolved_urls,
        )

        def pages() -> Iterator[tuple[str, bool]]:
            yield from local_pages
            # Only links actually seen on the company site. No external crawl,
            # guessed provider paths, or additional search API requests.
            yield from ((url, True) for url in external_candidates[:MAX_EXTERNAL_CONTACT_PAGES])

        provider = get_form_decision_provider() if allow_ai else None
        for url, explicit in pages():
            page_started = time.monotonic()
            try:
                requested_url = url
                external = url in external_seen
                html = root_cache.get(url)
                if html is None:
                    # Keep the same global request/time budget and pin navigation
                    # to this candidate's host before even fetching robots.txt.
                    fetcher.site_root = url if external else root.url
                    try:
                        page = fetcher.fetch_html(url)
                    finally:
                        fetcher.site_root = root.url
                    if not same_site(url if external else root.url, page.url):
                        raise ScrapeError(
                            "問い合わせページが別サイトへ転送されました。確認が必要です。"
                        )
                    resolved_urls[url] = page.url
                    root_cache[url] = page.html
                    url, html = page.url, page.html
                    root_cache[url] = html
                _log(
                    db,
                    company.id,
                    "contact_page_found",
                    details={
                        "url": url,
                        "requested_url": requested_url,
                        "discovery_method": "EXTERNAL_LINK"
                        if external
                        else "LINK"
                        if explicit
                        else "GUESSED_PATH",
                    },
                )
                soup = BeautifulSoup(html, "html.parser")
                if not external:
                    record_external_links(html, url)
                forms = list(soup.select("form"))
                full_text = soup.get_text(" ", strip=True)
                text = full_text[:30_000]
                # Sales notices often live in the footer, after the AI text cap.
                page_permission, page_prohibition = sales_contact_status(full_text, False)
                record_prohibition(page_prohibition, url)
                page_kind = _page_kind(url, text)
                if not any(is_contact_form(form) for form in forms):
                    embeds = embedded_form_providers(html)
                    _log(
                        db,
                        company.id,
                        "analysis_completed",
                        details={
                            "url": url,
                            "finding": "EMBEDDED_FORM_UNVERIFIED"
                            if embeds
                            else "DOM_CONTACT_FORM_NOT_FOUND",
                            "embedded_providers": embeds,
                        },
                    )
                    if explicit:
                        profile = _upsert_profile(
                            db,
                            company,
                            url,
                            0,
                            form_found=False,
                            page_kind=page_kind,
                            fields=[],
                            sales_status="PROHIBITED"
                            if "PROHIBITED" in {root_permission, page_permission}
                            else "UNCERTAIN",
                            captcha=_captcha_type(html),
                            confirmation=None,
                            duration_ms=round((time.monotonic() - page_started) * 1000),
                            provider_name="rule",
                        )
                        if embeds:
                            profile.review_reason = (
                                "外部埋め込みを検出しました（"
                                + ", ".join(embeds)
                                + "）。表示後のフォーム確認が必要です。"
                                "フォームなしとは判定していません。"
                            )[:500]
                        profiles.append(profile)
                        seen.add((url, 0))
                    continue
                for form_index, form in enumerate(forms):
                    if not is_contact_form(form):
                        continue
                    form_started = time.monotonic()
                    compatibility = assess_delivery_compatibility(form, url)
                    fields = parse_form_fields(form)
                    sales_status, prohibition = sales_contact_status(
                        f"{text} {form.get_text(' ', strip=True)}", True
                    )
                    if root_permission == "PROHIBITED":
                        sales_status, prohibition = "PROHIBITED", root_prohibition
                    elif page_permission == "PROHIBITED":
                        sales_status, prohibition = "PROHIBITED", page_prohibition
                    elif external and sales_status != "PROHIBITED":
                        # Provider form existence does not prove company identity
                        # or permission to use a shared service for sales.
                        sales_status = "UNCERTAIN"
                    captcha = _captcha_type(str(form) + html)
                    confirmation = _confirmation_page(form)
                    provider_name = "rule"
                    ambiguous = [
                        AmbiguousField(
                            position=item["position"],
                            label=item["label"],
                            name=item["name"],
                            field_type=item["field_type"],
                            required=item["required"],
                            options=item["options"],
                        )
                        for item in fields
                        if item["mapped_key"] == "unknown"
                        and item["field_type"]
                        not in {"hidden", "submit", "button", "reset", "image"}
                    ]
                    if provider and ambiguous and sales_status != "PROHIBITED":
                        _log(
                            db,
                            company.id,
                            "ai_decision_requested",
                            provider=provider.name,
                            details={"field_count": len(ambiguous)},
                        )
                        try:
                            batch = provider.decide(
                                DecisionContext(
                                    sales_objective=project.sales_objective if project else "",
                                    page_text=text[:5000],
                                    fields=ambiguous,
                                )
                            )
                            provider_name = batch.provider
                            ambiguous_positions = {item.position for item in ambiguous}
                            by_position = {
                                item.position: item
                                for item in batch.decisions
                                if item.position in ambiguous_positions
                            }
                            for item in fields:
                                decision = by_position.get(item["position"])
                                if decision:
                                    item["mapped_key"] = decision.mapped_key
                                    item["confidence"] = decision.confidence
                                    item["recommended_value"] = decision.recommended_value
                                    item["decision_source"] = batch.provider.upper()
                            _log(
                                db,
                                company.id,
                                "ai_decision_completed",
                                provider=batch.provider,
                                duration_ms=batch.duration_ms,
                                usage=batch.usage,
                                estimated_cost=batch.estimated_cost,
                            )
                        except FormDecisionError as exc:
                            _log(
                                db,
                                company.id,
                                "analysis_failed",
                                provider=provider.name,
                                details={"stage": "decision_provider", "reason": str(exc)[:500]},
                            )
                    for item in fields:
                        if (
                            item["mapped_key"] == "contact_category"
                            and not item["recommended_value"]
                        ):
                            value, confidence = recommended_option(
                                item["options"], project.sales_objective if project else ""
                            )
                            item["recommended_value"] = value
                            if value:
                                item["confidence"] = max(item["confidence"], confidence)
                        _log(
                            db,
                            company.id,
                            "field_detected",
                            details={"position": item["position"], "type": item["field_type"]},
                        )
                        _log(
                            db,
                            company.id,
                            "field_mapped",
                            provider=item["decision_source"].lower(),
                            confidence=item["confidence"],
                            details={
                                "position": item["position"],
                                "mapped_key": item["mapped_key"],
                            },
                        )
                    profile = _upsert_profile(
                        db,
                        company,
                        url,
                        form_index,
                        form_found=True,
                        page_kind=page_kind,
                        fields=fields,
                        sales_status=sales_status,
                        captcha=captcha,
                        confirmation=confirmation,
                        duration_ms=round((time.monotonic() - form_started) * 1000),
                        provider_name=provider_name,
                        delivery_supported=compatibility.supported,
                        compatibility_reason=compatibility.reason,
                        action_url=_clean_url(str(form.get("action") or url), url),
                    )
                    profiles.append(profile)
                    seen.add((url, form_index))
                    _log(
                        db,
                        company.id,
                        "form_found",
                        profile_id=profile.id,
                        details={"url": url, "form_index": form_index},
                    )
                    if captcha != "CAPTCHA_NONE":
                        _log(
                            db,
                            company.id,
                            "captcha_detected",
                            profile_id=profile.id,
                            details={"captcha_type": captcha},
                        )
                    if prohibition:
                        record_prohibition(prohibition, url)
                        _log(
                            db,
                            company.id,
                            "sales_prohibition_detected",
                            profile_id=profile.id,
                            details={"matched_text": prohibition},
                        )
                    _log(
                        db,
                        company.id,
                        "analysis_completed",
                        profile_id=profile.id,
                        duration_ms=profile.analysis_duration_ms,
                        details={"status": profile.form_status},
                    )
            except ScrapeError as exc:
                if explicit:
                    profile = _upsert_profile(
                        db,
                        company,
                        url,
                        0,
                        form_found=False,
                        page_kind="general",
                        fields=[],
                        sales_status="UNCERTAIN",
                        captcha="CAPTCHA_NONE",
                        confirmation=None,
                        duration_ms=round((time.monotonic() - page_started) * 1000),
                        provider_name="rule",
                        error_message=exc.public_message,
                    )
                    profiles.append(profile)
                    seen.add((url, 0))
                    _log(
                        db,
                        company.id,
                        "analysis_failed",
                        profile_id=profile.id,
                        details={
                            "reason": exc.public_message,
                            "finding": "FETCH_FAILED",
                            "url": url,
                        },
                    )
                else:
                    _log(
                        db,
                        company.id,
                        "analysis_failed",
                        details={
                            "reason": exc.public_message,
                            "finding": "FETCH_FAILED",
                            "url": url,
                            "discovery_method": "GUESSED_PATH",
                        },
                    )

        existing = db.scalars(select(FormProfile).where(FormProfile.company_id == company.id)).all()
        for profile in existing:
            if (profile.form_url, profile.form_index) not in seen and profile not in profiles:
                profile.form_status = "STALE"
                profile.is_primary = False
        if not profiles:
            profile = _upsert_profile(
                db,
                company,
                root.url,
                0,
                form_found=False,
                page_kind="general",
                fields=[],
                sales_status="UNCERTAIN",
                captcha="CAPTCHA_NONE",
                confirmation=None,
                duration_ms=round((time.monotonic() - started) * 1000),
                provider_name="rule",
            )
            profiles.append(profile)
        current_primary = next((item for item in profiles if item.is_primary), None)
        if current_primary is None:
            rank = {"READY": 0, "REVIEW_REQUIRED": 1, "STALE": 2, "BLOCKED": 3, "ERROR": 4}
            kind_rank = {
                "partnership": 0,
                "general": 1,
                "document_request": 2,
                "support": 3,
                "recruitment": 4,
            }
            primary = min(
                profiles,
                key=lambda item: (
                    rank.get(item.form_status, 9),
                    kind_rank.get(item.page_kind, 9),
                    item.form_index,
                ),
            )
            for current_profile in profiles:
                current_profile.is_primary = current_profile.id == primary.id
        db.commit()
        return list(
            db.scalars(
                select(FormProfile)
                .where(FormProfile.company_id == company.id)
                .order_by(
                    FormProfile.is_primary.desc(), FormProfile.form_url, FormProfile.form_index
                )
            ).all()
        )
    except ScrapeError as exc:
        db.rollback()
        for matched, source_url in tuple(prohibitions):
            record_prohibition(matched, source_url)
        profile = _upsert_profile(
            db,
            company,
            company.website_url,
            0,
            form_found=False,
            page_kind="general",
            fields=[],
            sales_status="UNCERTAIN",
            captcha="CAPTCHA_NONE",
            confirmation=None,
            duration_ms=round((time.monotonic() - started) * 1000),
            provider_name="rule",
            error_message=exc.public_message,
        )
        _log(
            db,
            company.id,
            "analysis_failed",
            profile_id=profile.id,
            details={"reason": exc.public_message, "finding": "FETCH_FAILED"},
        )
        db.commit()
        return [profile]
    except Exception as exc:
        db.rollback()
        for matched, source_url in tuple(prohibitions):
            record_prohibition(matched, source_url)
        logger.error(
            "form intelligence error: company_id=%s type=%s",
            company.id,
            type(exc).__name__,
        )
        profile = _upsert_profile(
            db,
            company,
            company.website_url,
            0,
            form_found=False,
            page_kind="general",
            fields=[],
            sales_status="UNCERTAIN",
            captcha="CAPTCHA_NONE",
            confirmation=None,
            duration_ms=round((time.monotonic() - started) * 1000),
            provider_name="rule",
            error_message="フォーム解析中にエラーが発生しました。",
        )
        _log(
            db,
            company.id,
            "analysis_failed",
            profile_id=profile.id,
            details={"reason": profile.error_message},
        )
        db.commit()
        return [profile]
    finally:
        fetcher.close()
