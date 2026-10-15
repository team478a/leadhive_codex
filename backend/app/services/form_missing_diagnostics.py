from collections import Counter
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, FormAnalysisLog, FormProfile

REASON_ORDER = (
    "ROOT_FETCH_FAILED",
    "BUDGET_EXHAUSTED",
    "ROBOTS_OR_REDIRECT",
    "EMBED_UNVERIFIED",
    "CUSTOM_CONTROLS",
    "PAGE_FOUND_NO_FORM",
    "GUESSED_PATH_ONLY",
    "NO_CONTACT_PAGE",
    "UNKNOWN_LEGACY",
)
REASON_LABELS = {
    "ROOT_FETCH_FAILED": "トップページ取得失敗",
    "BUDGET_EXHAUSTED": "取得上限到達",
    "ROBOTS_OR_REDIRECT": "robots拒否・転送",
    "EMBED_UNVERIFIED": "埋め込み未確認",
    "CUSTOM_CONTROLS": "独自入力欄候補",
    "PAGE_FOUND_NO_FORM": "問い合わせページ到達・フォームなし",
    "GUESSED_PATH_ONLY": "推測URLのみ試行",
    "NO_CONTACT_PAGE": "問い合わせページ未到達",
    "UNKNOWN_LEGACY": "旧解析・情報不足",
}
EXCLUDED_STATUSES = ("UNANALYZED", "ERROR", "STALE", "BLOCKED")


def missing_form_candidates_query(project_id: UUID):
    latest = (
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
        .where(Company.project_id == project_id)
        .subquery()
    )
    return (
        select(Company, FormProfile)
        .join(latest, latest.c.company_id == Company.id)
        .join(FormProfile, FormProfile.id == latest.c.profile_id)
        .where(
            latest.c.position == 1,
            Company.analysis_status == "completed",
            Company.website_url.is_not(None),
            Company.do_not_contact.is_(False),
            FormProfile.form_status.notin_(EXCLUDED_STATUSES),
            FormProfile.sales_contact_status != "PROHIBITED",
            FormProfile.form_found.is_(False),
        )
        .order_by(Company.created_at, Company.id)
    )


def _version_is_legacy(version: str) -> bool:
    try:
        current = tuple(int(part) for part in version.split(".")[:2])
        return current < (2, 2)
    except (TypeError, ValueError):
        return True


def classify_missing_form(
    profile: FormProfile, logs: list[FormAnalysisLog], website_url: str
) -> dict:
    starts = [index for index, log in enumerate(logs) if log.event_type == "analysis_started"]
    current_logs = logs[starts[-1] :] if starts else logs
    pages = [log for log in current_logs if log.event_type == "contact_page_found"]
    failures = [log for log in current_logs if log.event_type == "analysis_failed"]
    completions = [log for log in current_logs if log.event_type == "analysis_completed"]
    methods = [str(log.details.get("discovery_method") or "") for log in [*pages, *failures]]
    root_url = website_url.rstrip("/")
    reached_urls = [
        str(log.details.get("url") or "")
        for log in pages
        if str(log.details.get("url") or "").rstrip("/") != root_url
    ]
    reasons: set[str] = set()
    root_failure = any(
        not str(log.details.get("url") or "")
        or str(log.details.get("url") or "").rstrip("/") == root_url
        for log in failures
    )
    if failures and not pages and root_failure:
        reasons.add("ROOT_FETCH_FAILED")
    failure_text = " ".join(str(log.details.get("reason") or "") for log in failures).casefold()
    if any(word in failure_text for word in ("上限", "回数", "timeout", "timed out", "budget")):
        reasons.add("BUDGET_EXHAUSTED")
    if any(word in failure_text for word in ("robots", "別サイト", "転送", "redirect")):
        reasons.add("ROBOTS_OR_REDIRECT")
    findings = {str(log.details.get("finding") or "") for log in completions}
    if "EMBEDDED_FORM_UNVERIFIED" in findings:
        reasons.add("EMBED_UNVERIFIED")
    if "CUSTOM_CONTACT_CONTROLS_CANDIDATE" in findings:
        reasons.add("CUSTOM_CONTROLS")
    if "DOM_CONTACT_FORM_NOT_FOUND" in findings and any(
        method in {"LINK", "EXTERNAL_LINK"} for method in methods
    ):
        reasons.add("PAGE_FOUND_NO_FORM")
    if "GUESSED_PATH" in methods and not any(
        method in {"LINK", "EXTERNAL_LINK"} for method in methods
    ):
        reasons.add("GUESSED_PATH_ONLY")
    if not reached_urls:
        reasons.add("NO_CONTACT_PAGE")
    if _version_is_legacy(profile.analysis_version):
        reasons.add("UNKNOWN_LEGACY")
    ordered = [reason for reason in REASON_ORDER if reason in reasons]
    if not ordered:
        ordered = ["UNKNOWN_LEGACY"]
    return {
        "primary_reason": ordered[0],
        "secondary_reasons": ordered[1:],
        "last_reached_url": reached_urls[-1] if reached_urls else "",
        "analysis_version": profile.analysis_version,
        "analyzed_at": profile.last_analyzed_at,
    }


def collect_missing_diagnostics(db: Session, project_id: UUID) -> tuple[dict[str, int], list[dict]]:
    candidates = db.execute(missing_form_candidates_query(project_id)).all()
    company_ids = [company.id for company, _profile in candidates]
    logs_by_company: dict[UUID, list[FormAnalysisLog]] = {
        company_id: [] for company_id in company_ids
    }
    if company_ids:
        logs = db.scalars(
            select(FormAnalysisLog)
            .where(
                FormAnalysisLog.company_id.in_(company_ids),
                FormAnalysisLog.event_type.in_(
                    (
                        "analysis_started",
                        "analysis_failed",
                        "contact_page_found",
                        "analysis_completed",
                    )
                ),
            )
            .order_by(FormAnalysisLog.company_id, FormAnalysisLog.created_at, FormAnalysisLog.id)
        ).all()
        for log in logs:
            logs_by_company[log.company_id].append(log)
    rows = []
    counts: Counter[str] = Counter()
    for company, profile in candidates:
        diagnostic = classify_missing_form(
            profile, logs_by_company[company.id], company.website_url or ""
        )
        counts[diagnostic["primary_reason"]] += 1
        rows.append(
            {
                "company_id": company.id,
                "company_name": company.company_name,
                "website_url": company.website_url or "",
                **diagnostic,
            }
        )
    return {reason: counts[reason] for reason in REASON_ORDER if counts[reason]}, rows
