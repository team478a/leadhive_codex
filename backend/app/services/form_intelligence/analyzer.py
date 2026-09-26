import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Company, FormAnalysisLog, FormProfile, FormProfileField, Project
from app.services.form_intelligence.fingerprint import form_fingerprint
from app.services.form_intelligence.providers import (
    AmbiguousField,
    DecisionContext,
    FormDecisionError,
    get_form_decision_provider,
)
from app.services.form_intelligence.rules import (
    dom_mapping,
    recommended_option,
    rule_mapping,
    sales_contact_status,
)
from app.services.scraper import CONTACT_HINTS, SafeFetcher, ScrapeError

logger = logging.getLogger("leadhive")
ANALYSIS_VERSION = "1.0"
MAX_CONTACT_PAGES = 8
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


def _field_label(element: Tag, form: Tag) -> str:
    element_id = str(element.get("id") or "")
    if element_id:
        label = form.find("label", attrs={"for": element_id})
        if label:
            return label.get_text(" ", strip=True)[:500]
    parent = element.find_parent("label")
    if parent:
        return parent.get_text(" ", strip=True)[:500]
    for attribute in ("aria-label", "placeholder", "name"):
        if element.get(attribute):
            return str(element.get(attribute))[:500]
    return "入力項目"


def _selector(element: Tag, position: int) -> str:
    element_id = str(element.get("id") or "").replace('"', "")
    name = str(element.get("name") or "").replace('"', "")
    if element_id:
        return f'{element.name}[id="{element_id}"]'
    if name:
        return f'{element.name}[name="{name}"]'
    return f"{element.name}:nth-of-type({position + 1})"


def _option(element: Tag) -> dict[str, str]:
    label = element.get_text(" ", strip=True)[:500]
    return {"value": str(element.get("value") or label)[:500], "label": label}


def _parse_fields(form: Tag) -> list[dict]:
    fields: list[dict] = []
    grouped: set[tuple[str, str]] = set()
    elements = form.select("input, textarea, select, button")
    for element in elements:
        if element.has_attr("disabled"):
            continue
        raw_type = str(element.get("type") or "text").lower()
        if element.name == "textarea":
            field_type = "textarea"
        elif element.name == "select":
            field_type = "select"
        elif element.name == "button":
            field_type = "button"
        else:
            field_type = raw_type
        name = str(element.get("name") or "")[:500]
        group_key = (field_type, name)
        if field_type in {"radio", "checkbox"} and name:
            if group_key in grouped:
                continue
            grouped.add(group_key)
            group = form.find_all("input", attrs={"type": field_type, "name": name})
            options = [
                {
                    "value": str(item.get("value") or "")[:500],
                    "label": _field_label(item, form),
                }
                for item in group
            ]
            required = any(
                item.has_attr("required") or str(item.get("aria-required") or "").lower() == "true"
                for item in group
            )
        else:
            options = [_option(item) for item in element.select("option")]
            required = element.has_attr("required") or str(
                element.get("aria-required") or ""
            ).lower() == "true"
        position = len(fields)
        label = _field_label(element, form)
        parent = element.find_parent(["div", "p", "li", "td", "fieldset"])
        surrounding = parent.get_text(" ", strip=True)[:1000] if parent else label
        mapped = dom_mapping(field_type, name)
        if field_type in {"hidden", "submit", "button", "reset", "image"}:
            mapped_key, confidence, source = "other", 1.0, "DOM"
        elif mapped:
            mapped_key, confidence, source = mapped[0], mapped[1], "DOM"
        else:
            mapping_text = " ".join(
                filter(
                    None,
                    (
                        label,
                        name,
                        str(element.get("id") or ""),
                        str(element.get("placeholder") or ""),
                        str(element.get("aria-label") or ""),
                        surrounding,
                    ),
                )
            )
            mapped_key, confidence = rule_mapping(mapping_text, field_type)
            source = "RULE"
        fields.append(
            {
                "position": position,
                "selector": _selector(element, position),
                "element_id": str(element.get("id") or "")[:500],
                "label": label,
                "name": name,
                "field_type": field_type[:50],
                "required": required,
                "mapped_key": mapped_key,
                "confidence": confidence,
                "decision_source": source,
                "recommended_value": "",
                "options": options,
                "placeholder": str(element.get("placeholder") or "")[:500],
                "aria_label": str(element.get("aria-label") or "")[:500],
                "surrounding_text": surrounding,
            }
        )
    return fields


def _captcha_type(html: str) -> str:
    value = html.lower()
    if "hcaptcha" in value:
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
) -> str:
    if sales_status == "PROHIBITED":
        return "BLOCKED"
    if not form_found or sales_status == "UNCERTAIN" or captcha != "CAPTCHA_NONE":
        return "REVIEW_REQUIRED"
    relevant = [
        item
        for item in fields
        if item["field_type"] not in {"hidden", "submit", "button", "reset", "image"}
    ]
    if confirmation is None or any(
        item["required"] and (item["mapped_key"] == "unknown" or item["confidence"] < 0.8)
        for item in relevant
    ):
        return "REVIEW_REQUIRED"
    return "READY"


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
    error_message: str = "",
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
    fingerprint = form_fingerprint(fields) if fields else ""
    status = (
        "ERROR"
        if error_message
        else _profile_status(form_found, sales_status, captcha, confirmation, fields)
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
    profile.analysis_version = ANALYSIS_VERSION
    profile.analysis_provider = provider_name
    profile.last_analyzed_at = datetime.now(timezone.utc)
    profile.analysis_duration_ms = max(0, duration_ms)
    profile.error_message = error_message[:500]
    db.execute(delete(FormProfileField).where(FormProfileField.form_profile_id == profile.id))
    for item in fields:
        manual_value = manual.get((item["name"], item["selector"]))
        if manual_value:
            item["mapped_key"], item["recommended_value"] = manual_value
            item["confidence"], item["decision_source"] = 1.0, "MANUAL"
        db.add(
            FormProfileField(
                form_profile_id=profile.id,
                **{key: value for key, value in item.items() if key != "element_id"},
            )
        )
    return profile


def analyze_company_forms(db: Session, company: Company, force: bool = False) -> list[FormProfile]:
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
    try:
        root = fetcher.fetch_html(company.website_url)
        pages = _candidate_pages(company, root.url, root.html)
        root_cache = {root.url: root.html}
        if not pages:
            pages = [(root.url, True)]
        provider = get_form_decision_provider()
        for url, explicit in pages:
            page_started = time.monotonic()
            try:
                html = root_cache.get(url)
                if html is None:
                    page = fetcher.fetch_html(url)
                    url, html = page.url, page.html
                _log(db, company.id, "contact_page_found", details={"url": url})
                soup = BeautifulSoup(html, "html.parser")
                forms = list(soup.select("form"))
                text = soup.get_text(" ", strip=True)[:30_000]
                page_kind = _page_kind(url, text)
                if not forms:
                    if explicit:
                        profile = _upsert_profile(
                            db,
                            company,
                            url,
                            0,
                            form_found=False,
                            page_kind=page_kind,
                            fields=[],
                            sales_status="UNCERTAIN",
                            captcha=_captcha_type(html),
                            confirmation=None,
                            duration_ms=round((time.monotonic() - page_started) * 1000),
                            provider_name="rule",
                        )
                        profiles.append(profile)
                        seen.add((url, 0))
                    continue
                for form_index, form in enumerate(forms):
                    form_started = time.monotonic()
                    fields = _parse_fields(form)
                    sales_status, prohibition = sales_contact_status(
                        f"{text} {form.get_text(' ', strip=True)}", True
                    )
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
                    if provider and ambiguous:
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
                            by_position = {item.position: item for item in batch.decisions}
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
                        details={"reason": exc.public_message},
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
            for item in profiles:
                item.is_primary = item.id == primary.id
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
            details={"reason": exc.public_message},
        )
        db.commit()
        return [profile]
    except Exception as exc:
        db.rollback()
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
