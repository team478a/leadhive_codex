"""Read-only browser analysis for previously identified contact pages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from bs4 import BeautifulSoup
from bs4.element import Tag
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import Company, FormProfile
from app.services.contact_discovery import (
    custom_contact_containers,
    embedded_form_providers,
    is_contact_form,
    is_contact_path,
    same_site,
)
from app.services.form_intelligence.analyzer import (
    _captcha_type,
    _clean_url,
    _confirmation_page,
    _log,
    _page_kind,
    _upsert_profile,
)
from app.services.form_intelligence.compatibility import (
    DeliveryCompatibility,
    assess_delivery_compatibility,
)
from app.services.form_intelligence.fields import parse_form_fields
from app.services.form_intelligence.rules import sales_contact_status
from app.services.pinned_read_transport import TransportBlocked
from app.services.pinned_read_transport import target as validate_target

MAX_BROWSER_ANALYSIS_TARGETS = 100
SUPPORTED_FORM_REASONS = {
    "CONTACT_FORM_7",
    "MULTIPART_OR_FILE",
    "JAVASCRIPT_CONFIRMATION",
    "ASYNC_SUBMISSION",
}
EMBED_UNVERIFIED_MARKER = "外部埋め込みを検出しました"
NO_FORM_MARKER = "送信可能なフォームが見つかりません"
CONTACT_PATH_PATTERN = (
    r"(?:^|[/_-])(?:contact|inquiry|inquire|otoiawase|toiawase|form|mailform|"
    r"estimate|mitsumori|soudan)(?:$|[/_.-])"
)


@dataclass(frozen=True)
class BrowserAnalysisTarget:
    company_id: UUID
    profile_id: UUID
    url: str
    site_host: str
    form_index: int


@dataclass(frozen=True)
class RenderedForm:
    form_index: int
    form: Tag | None
    fields: list[dict]
    compatibility: DeliveryCompatibility
    captcha_type: str
    confirmation_page: bool | None
    sales_contact_status: str
    prohibition: str
    fingerprint: str
    form_found: bool
    page_kind: str
    review_reason: str
    action_url: str


def _target_url(company: Company, profile: FormProfile) -> tuple[str, str] | None:
    try:
        site_host = validate_target(company.website_url or "")
        form_host = validate_target(profile.form_url or "")
    except (TransportBlocked, TypeError):
        return None
    if not same_site(company.website_url, profile.form_url):
        return None
    parsed = urlsplit(profile.form_url)
    url = urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))
    if form_host.removeprefix("www.") != site_host.removeprefix("www."):
        return url, ""
    return url, site_host


def _eligible_profile_filter():
    known_contact_page = or_(
        Company.contact_url == FormProfile.form_url,
        FormProfile.form_url.op("~*")(CONTACT_PATH_PATTERN),
    )
    no_form_contact_page = and_(
        FormProfile.form_found.is_(False),
        FormProfile.error_message == "",
        or_(
            FormProfile.review_reason.ilike(f"%{EMBED_UNVERIFIED_MARKER}%"),
            and_(FormProfile.review_reason.ilike(f"%{NO_FORM_MARKER}%"), known_contact_page),
        ),
    )
    supported_form = and_(
        FormProfile.form_found.is_(True),
        or_(
            FormProfile.compatibility_reason_code.in_(SUPPORTED_FORM_REASONS),
            FormProfile.confirmation_page.is_(True),
        ),
    )
    return and_(
        FormProfile.analysis_source != "browser",
        FormProfile.sales_contact_status != "PROHIBITED",
        or_(no_form_contact_page, supported_form),
    )


def eligible_no_form_profile(company: Company, profile: FormProfile) -> bool:
    reason = profile.review_reason or ""
    if profile.form_found or profile.error_message:
        return False
    if EMBED_UNVERIFIED_MARKER in reason:
        return True
    return NO_FORM_MARKER in reason and (
        company.contact_url == profile.form_url or is_contact_path(profile.form_url or "")
    )


def select_browser_analysis_targets(
    db: Session, project_id: UUID, *, limit: int = MAX_BROWSER_ANALYSIS_TARGETS
) -> list[BrowserAnalysisTarget]:
    if limit < 1 or limit > MAX_BROWSER_ANALYSIS_TARGETS:
        raise ValueError("Browser analysis target limit must be between 1 and 100.")
    ranked = (
        select(
            FormProfile.id.label("profile_id"),
            FormProfile.company_id.label("company_id"),
            func.row_number()
            .over(
                partition_by=FormProfile.company_id,
                order_by=(
                    FormProfile.is_primary.desc(),
                    FormProfile.updated_at.desc(),
                    FormProfile.id,
                ),
            )
            .label("position"),
        )
        .join(Company, Company.id == FormProfile.company_id)
        .where(
            Company.project_id == project_id,
            Company.record_type == "company",
            Company.do_not_contact.is_(False),
            Company.website_url.ilike("https://%"),
            _eligible_profile_filter(),
        )
        .subquery()
    )
    rows = db.execute(
        select(Company, FormProfile)
        .join(ranked, (ranked.c.company_id == Company.id) & (ranked.c.position == 1))
        .join(FormProfile, FormProfile.id == ranked.c.profile_id)
        .where(
            Company.project_id == project_id,
            Company.record_type == "company",
            Company.do_not_contact.is_(False),
            Company.website_url.ilike("https://%"),
            _eligible_profile_filter(),
        )
        .order_by(Company.company_name, Company.id)
        .limit(limit * 10)
    ).all()
    targets: list[BrowserAnalysisTarget] = []
    for company, profile in rows:
        target = _target_url(company, profile)
        if target is None or not target[1]:
            continue
        url, site_host = target
        targets.append(
            BrowserAnalysisTarget(
                company_id=company.id,
                profile_id=profile.id,
                url=url,
                site_host=site_host,
                form_index=profile.form_index,
            )
        )
        if len(targets) >= limit:
            break
    return targets


def _control_signature(control: Tag) -> dict:
    signature = {
        "tag": control.name,
        "name": str(control.get("name") or ""),
        "id": str(control.get("id") or ""),
        "type": str(control.get("type") or "").lower(),
        "required": control.has_attr("required"),
        "disabled": control.has_attr("disabled"),
        "multiple": control.has_attr("multiple"),
        "placeholder": str(control.get("placeholder") or ""),
        "aria_label": str(control.get("aria-label") or ""),
    }
    if control.name == "select":
        signature["options"] = [
            {
                "value": str(option.get("value") or ""),
                "label": option.get_text(" ", strip=True),
                "disabled": option.has_attr("disabled"),
            }
            for option in control.select("option")[:100]
        ]
    if control.name in {"button", "input"} and signature["type"] in {"submit", "button"}:
        signature["label"] = control.get_text(" ", strip=True) or str(control.get("value") or "")
    return signature


def rendered_dom_fingerprint(
    url: str, form: Tag | None, fields: list[dict], page: BeautifulSoup
) -> str:
    controls = (
        form.select("input, textarea, select, button")
        if form
        else page.select("input, textarea, select, button, [role='textbox']")
    )
    form_signature = None
    if form is not None:
        form_signature = {
            "method": str(form.get("method") or "get").lower(),
            "enctype": str(form.get("enctype") or "").lower(),
            "action": _clean_url(str(form.get("action") or url), url),
            "controls": [_control_signature(control) for control in controls[:200]],
        }
    payload = {
        "form": form_signature,
        "page_controls": [_control_signature(control) for control in controls[:200]]
        if form is None
        else [],
        "fields": [
            {
                key: item.get(key)
                for key in (
                    "position",
                    "selector",
                    "label",
                    "name",
                    "field_type",
                    "required",
                    "options",
                    "placeholder",
                    "aria_label",
                )
            }
            for item in fields
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inspect_rendered_dom(html: str, url: str) -> list[RenderedForm]:
    page = BeautifulSoup(html, "html.parser")
    full_text = page.get_text(" ", strip=True)
    text = full_text[:30_000]
    page_permission, page_prohibition = sales_contact_status(full_text, False)
    page_kind = _page_kind(url, text)
    contact_forms = [
        form for form in page.select("form") if is_contact_form(form, contact_context=True)
    ]
    results: list[RenderedForm] = []
    for form_index, form in enumerate(contact_forms):
        fields = parse_form_fields(form)
        compatibility = assess_delivery_compatibility(form, url)
        sales_status, prohibition = sales_contact_status(
            f"{full_text} {form.get_text(' ', strip=True)}", True
        )
        if page_permission == "PROHIBITED":
            sales_status, prohibition = page_permission, page_prohibition
        results.append(
            RenderedForm(
                form_index=form_index,
                form=form,
                fields=fields,
                compatibility=compatibility,
                captcha_type=_captcha_type(html, form),
                confirmation_page=_confirmation_page(form),
                sales_contact_status=sales_status,
                prohibition=prohibition,
                fingerprint=rendered_dom_fingerprint(url, form, fields, page),
                form_found=True,
                page_kind=page_kind,
                review_reason=compatibility.reason,
                action_url=_clean_url(str(form.get("action") or url), url),
            )
        )
    if results:
        return results

    custom = custom_contact_containers(html)
    if len(custom) == 1:
        container = custom[0]
        fields = parse_form_fields(container)
        sales_status, prohibition = sales_contact_status(full_text, True)
        if page_permission == "PROHIBITED":
            sales_status, prohibition = page_permission, page_prohibition
        return [
            RenderedForm(
                form_index=0,
                form=None,
                fields=fields,
                compatibility=DeliveryCompatibility(
                    False,
                    "描画後DOMにJavaScript制御の問い合わせ入力欄があります。送信経路は未検証です。",
                    "ASYNC_SUBMISSION",
                ),
                captcha_type=_captcha_type(html),
                confirmation_page=None,
                sales_contact_status=sales_status,
                prohibition=prohibition,
                fingerprint=rendered_dom_fingerprint(url, None, fields, page),
                form_found=True,
                page_kind=page_kind,
                review_reason="描画後DOMでJavaScript制御の問い合わせ入力欄を検出しました。",
                action_url="",
            )
        ]

    providers = embedded_form_providers(html)
    no_form_reason = "ブラウザ描画後の問い合わせページにフォームがありません。"
    if providers:
        no_form_reason = (
            "描画後DOMで外部埋め込みを検出しました（"
            + ", ".join(providers)
            + "）。外部ドメインは開かず、埋め込みの表示確認は未実施です。"
        )
    sales_status = "PROHIBITED" if page_permission == "PROHIBITED" else "UNCERTAIN"
    return [
        RenderedForm(
            form_index=0,
            form=None,
            fields=[],
            compatibility=DeliveryCompatibility(False, no_form_reason, "NO_INPUT_FIELDS"),
            captcha_type=_captcha_type(html),
            confirmation_page=None,
            sales_contact_status=sales_status,
            prohibition=page_prohibition,
            fingerprint=rendered_dom_fingerprint(url, None, [], page),
            form_found=False,
            page_kind=page_kind,
            review_reason=no_form_reason,
            action_url="",
        )
    ]


def save_rendered_analysis(
    db: Session,
    company: Company,
    target_profile_id: UUID,
    url: str,
    html: str,
    duration_ms: int,
) -> list[FormProfile]:
    original = db.get(FormProfile, target_profile_id)
    stored_url = ""
    if original is not None:
        parsed = urlsplit(original.form_url)
        stored_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, "")
        )
    if original is None or original.company_id != company.id or stored_url != url:
        raise ValueError("The browser analysis target changed before it could be saved.")
    results = inspect_rendered_dom(html, url)
    _log(db, company.id, "analysis_started", profile_id=original.id, details={"source": "browser"})
    was_primary = original.is_primary
    found_indices = {item.form_index for item in results if item.form_found}
    profiles: list[FormProfile] = []
    if any(item.form_found for item in results):
        if original.form_index not in found_indices:
            original.form_found = False
            original.form_status = "STALE"
            original.analysis_source = "browser"
            original.is_primary = False
        first_found_index = next(item.form_index for item in results if item.form_found)
        for item in results:
            profile = _upsert_profile(
                db,
                company,
                url,
                item.form_index,
                form_found=item.form_found,
                page_kind=item.page_kind,
                fields=item.fields,
                sales_status=item.sales_contact_status,
                captcha=(
                    original.captcha_type
                    if item.captcha_type == "CAPTCHA_NONE"
                    and original.captcha_type != "CAPTCHA_NONE"
                    else item.captcha_type
                ),
                confirmation=item.confirmation_page,
                duration_ms=duration_ms,
                provider_name="browser",
                delivery_supported=item.compatibility.supported,
                compatibility_reason=item.review_reason or item.compatibility.reason,
                compatibility_reason_code=item.compatibility.reason_code,
                action_url=item.action_url,
                analysis_source="browser",
                fingerprint_override=item.fingerprint,
                review_reason_override=item.review_reason,
            )
            if was_primary and item.form_index == first_found_index:
                profile.is_primary = True
            profiles.append(profile)
            if item.prohibition:
                company.do_not_contact = True
                if not (company.exclusion_reason or "").startswith("営業NG："):
                    company.exclusion_reason = (
                        f"営業NG：{item.prohibition} / {company.exclusion_reason or ''}"
                    )[:500]
                _log(
                    db,
                    company.id,
                    "sales_prohibition_detected",
                    profile_id=profile.id,
                    details={"matched_text": item.prohibition, "source": "browser"},
                )
            _log(
                db,
                company.id,
                "analysis_completed",
                profile_id=profile.id,
                duration_ms=duration_ms,
                details={"source": "browser", "form_found": item.form_found},
            )
    else:
        item = results[0]
        profile = _upsert_profile(
            db,
            company,
            url,
            original.form_index,
            form_found=False,
            page_kind=item.page_kind,
            fields=[],
            sales_status=item.sales_contact_status,
            captcha=(
                original.captcha_type
                if item.captcha_type == "CAPTCHA_NONE" and original.captcha_type != "CAPTCHA_NONE"
                else item.captcha_type
            ),
            confirmation=None,
            duration_ms=duration_ms,
            provider_name="browser",
            delivery_supported=False,
            compatibility_reason=item.review_reason,
            compatibility_reason_code=item.compatibility.reason_code,
            action_url="",
            analysis_source="browser",
            fingerprint_override=item.fingerprint,
            review_reason_override=item.review_reason,
        )
        profile.is_primary = was_primary
        profiles.append(profile)
        if item.prohibition:
            company.do_not_contact = True
            if not (company.exclusion_reason or "").startswith("営業NG："):
                company.exclusion_reason = (
                    f"営業NG：{item.prohibition} / {company.exclusion_reason or ''}"
                )[:500]
            _log(
                db,
                company.id,
                "sales_prohibition_detected",
                profile_id=profile.id,
                details={"matched_text": item.prohibition, "source": "browser"},
            )
        _log(
            db,
            company.id,
            "analysis_completed",
            profile_id=profile.id,
            duration_ms=duration_ms,
            details={"source": "browser", "form_found": False},
        )
    db.flush()
    return profiles
