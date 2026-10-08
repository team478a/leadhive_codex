"""Cached, read-only destination diagnostics. Never authorizes or schedules delivery.

READY requires a current version-bound Human purpose attestation.
The canonical contact guard remains the sending authority; these are stricter
preparation diagnostics, not a second permission store.
"""

from datetime import datetime, timedelta, timezone

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, or_, select

from app.models import (
    ContactDestination,
    ContactPerson,
    EmailDelivery,
    FormDelivery,
    FormProfile,
    FormProfileField,
)
from app.services.contact_destinations import candidates, linked_inventory, normalize_destination
from app.services.contact_permission import evaluate_contact_permission
from app.services.destination_choice import public_choice
from app.services.destination_review import latest, public_review, snapshot_hash
from app.services.destination_selection import recommend
from app.services.form_intelligence.fields import mapping_review_reason
from app.services.site_identity_review import confirmation

DEFINITION = "sendability-b3-v1"
EMAIL = TypeAdapter(EmailStr)
REASONS = {
    "DESTINATION_SCOPE_UNCERTAIN": (
        "窓口の対象範囲が企業・店舗と一致していない",
        "対象範囲を確認する。共有窓口はREADYにしません",
    ),
    "DESTINATION_REVIEW_STALE": ("用途確認後に対象情報が変わった", "再読込し、根拠を再確認する"),
    "DESTINATION_REVIEW_EXPIRED": ("用途確認の有効期限切れ", "根拠を再確認する"),
    "DESTINATION_REVIEW_REVOKED": ("用途確認を取り消し済み", "必要な場合に根拠を再確認する"),
    "DO_NOT_CONTACT": ("連絡禁止", "連絡しない"),
    "SUPPRESSED": ("送信禁止リストに登録済み", "連絡しない"),
    "SALES_PROHIBITED": ("営業禁止の記録あり", "連絡しない"),
    "DELIVERY_UNKNOWN": ("過去の送信結果が不明", "人が結果を確認する。自動再送しない"),
    "DUPLICATE_DESTINATION": ("送信済み・処理中の窓口", "既存の送信履歴を確認する"),
    "OFFICIAL_SITE_NOT_FOUND": ("公式サイト未登録", "公式サイト候補を探す"),
    "IDENTITY_UNCERTAIN": (
        "企業・店舗と公式サイトの照合が未確認",
        "名称・住所・電話の照合根拠を確認する",
    ),
    "CONTACT_NOT_FOUND": ("窓口候補なし", "公式サイトで連絡先を確認する"),
    "DESTINATION_INVALID": ("窓口の形式・URLが不適切", "登録先を確認する"),
    "DESTINATION_PURPOSE_UNCERTAIN": (
        "用途の有効な確認証跡がない",
        "根拠を確認して用途確認を保存する。送信承認とは別の操作です",
    ),
    "DESTINATION_PURPOSE_UNSUITABLE": (
        "予約・採用・サポート専用の窓口",
        "営業目的に合う別の窓口を探す",
    ),
    "SHARED_DESTINATION": (
        "複数対象の共通窓口",
        "独立窓口または共有窓口への一度だけの対応を検討する",
    ),
    "CONTACT_INVALID": ("無効な連絡先", "有効な連絡先を確認する"),
    "EMAIL_UNVERIFIED": ("メールの品質が未確認", "連絡先品質と根拠を確認する"),
    "FORM_UNANALYZED": ("該当フォームの解析なし", "フォーム解析が必要"),
    "FORM_PROFILE_MISMATCH": ("選択候補と主フォームが異なる", "対象のフォームProfileを確認する"),
    "FORM_ANALYSIS_STALE": (
        "フォーム解析が古い・日時不明",
        "再解析が必要。送信時には実フォームも再確認する",
    ),
    "FORM_NOT_READY": ("フォームがREADYではない", "解析結果を確認する"),
    "SALES_PERMISSION_UNCERTAIN": ("営業利用可否が未確認", "禁止表記・窓口の用途を確認する"),
    "CAPTCHA": ("CAPTCHA・人の操作が必要", "Human Required。自動操作や回避は行わない"),
    "FORM_TECHNICALLY_UNSUPPORTED": (
        "通常経路の技術対応が未確認",
        "対応方式を確認する。送信は開始しない",
    ),
    "REQUIRED_FIELD_UNKNOWN": (
        "本文・必須項目の対応が未確認",
        "フォーム項目のマッピングを確認する",
    ),
    "FORM_FINGERPRINT_MISSING": ("フォーム構造の証拠がない", "再解析が必要"),
    "CONTACT_PERMISSION_UNCERTAIN": (
        "既存の連絡可否制御が許可していない",
        "連絡可否の理由を確認する",
    ),
}
CORE_CODES = {
    "company_do_not_contact": "DO_NOT_CONTACT",
    "form_sales_prohibited": "SALES_PROHIBITED",
    "form_result_unknown": "DELIVERY_UNKNOWN",
    "shared_location_destination": "SHARED_DESTINATION",
    "contact_quality_invalid": "CONTACT_INVALID",
}
HARD = {
    "DO_NOT_CONTACT",
    "SUPPRESSED",
    "SALES_PROHIBITED",
    "DELIVERY_UNKNOWN",
    "DUPLICATE_DESTINATION",
    "CONTACT_INVALID",
    "DESTINATION_INVALID",
}
HOLDS = {
    "OFFICIAL_SITE_NOT_FOUND",
    "CONTACT_NOT_FOUND",
    "FORM_UNANALYZED",
    "FORM_ANALYSIS_STALE",
    "FORM_TECHNICALLY_UNSUPPORTED",
    "REQUIRED_FIELD_UNKNOWN",
    "FORM_FINGERPRINT_MISSING",
    "DESTINATION_PURPOSE_UNSUITABLE",
}


def reason_details(codes):
    return [
        {"code": code, "message": REASONS[code][0], "next_action": REASONS[code][1]}
        for code in sorted(codes)
    ]


def status_for(codes):
    if codes & HARD:
        return "BLOCKED"
    if codes & HOLDS:
        return "HOLD"
    return "REVIEW" if codes else "READY"


def _key(channel, value):
    try:
        return normalize_destination(channel, value)
    except (ValueError, TypeError):
        return ""


def evaluate(db, company):
    now = datetime.now(timezone.utc)
    available = candidates(db, company)
    inventory = {(r["type"], r["destination"]): r for r in linked_inventory(db, company)}
    profiles = db.scalars(
        select(FormProfile)
        .where(FormProfile.company_id == company.id)
        .order_by(FormProfile.is_primary.desc(), FormProfile.updated_at.desc(), FormProfile.id)
    ).all()
    fields = db.scalars(
        select(FormProfileField).where(
            FormProfileField.form_profile_id.in_([p.id for p in profiles])
        )
    ).all()
    contacts = db.scalars(select(ContactPerson).where(ContactPerson.company_id == company.id)).all()
    confirmed = confirmation(db, company, now)
    # Read only; global delivery guards already reserve by company or destination.
    emails = [v for c, v in available if c == "email"]
    forms = [v for c, v in available if c == "form"]
    email_history = db.execute(
        select(EmailDelivery.recipient_email, EmailDelivery.status).where(
            or_(
                EmailDelivery.company_id == company.id,
                func.lower(func.trim(EmailDelivery.recipient_email)).in_(emails),
            ),
            EmailDelivery.status.in_(["queued", "running", "sent", "unknown"]),
        )
    ).all()
    form_history = db.execute(
        select(FormDelivery.form_url, FormDelivery.status).where(
            or_(
                FormDelivery.company_id == company.id,
                func.rtrim(FormDelivery.form_url, "/").in_(forms),
            ),
            FormDelivery.status.in_(["pending", "submitted", "unknown"]),
        )
    ).all()
    global_codes: set[str] = set()
    base = evaluate_contact_permission(
        db, company.project_id, company.id, "form", company.contact_url or ""
    )
    if company.do_not_contact:
        global_codes.add("DO_NOT_CONTACT")
    if base.reason_code.startswith("suppression_"):
        global_codes.add("SUPPRESSED")
    if base.reason_code == "form_result_unknown":
        global_codes.add("DELIVERY_UNKNOWN")
    # Sales prohibition is never bypassed by changing channel or selecting a
    # different (including non-primary/shared) profile.
    if any(p.sales_contact_status == "PROHIBITED" or p.form_status == "BLOCKED" for p in profiles):
        global_codes.add("SALES_PROHIBITED")
    if any(status == "unknown" for _, status in (*email_history, *form_history)):
        global_codes.add("DELIVERY_UNKNOWN")
    lead_codes = set(global_codes)
    if not company.website_url:
        lead_codes.add("OFFICIAL_SITE_NOT_FOUND")
    elif not confirmed:
        lead_codes.add("IDENTITY_UNCERTAIN")
    rows: list[dict] = []
    for (channel, value), source in sorted(available.items()):
        codes = set(lead_codes)
        saved = inventory.get((channel, value), {})
        purpose = saved.get("purpose", "unknown")
        destination = db.get(ContactDestination, saved["id"]) if saved.get("id") else None
        digest = snapshot_hash(db, company, destination) if destination else None
        review_row = latest(db, company.id, destination.id) if destination else None
        review = public_review(review_row, digest, now)
        if review["state"] == "CURRENT":
            purpose = review["purpose"]
            if review["scope"] != company.record_type:
                codes.add("DESTINATION_SCOPE_UNCERTAIN")
        else:
            codes.add("DESTINATION_PURPOSE_UNCERTAIN")
            if review["state"] in {"STALE", "EXPIRED", "REVOKED"}:
                codes.add("DESTINATION_REVIEW_" + review["state"])
        if purpose == "unknown":
            codes.add("DESTINATION_PURPOSE_UNCERTAIN")
        if purpose in {"support", "recruitment", "reservation"}:
            codes.add("DESTINATION_PURPOSE_UNSUITABLE")
        decision = evaluate_contact_permission(db, company.project_id, company.id, channel, value)
        if decision.reason_code.startswith("suppression_"):
            codes.add("SUPPRESSED")
        elif decision.reason_code in CORE_CODES:
            codes.add(CORE_CODES[decision.reason_code])
        elif not decision.allowed:
            codes.add("CONTACT_PERMISSION_UNCERTAIN")
        if saved.get("shared"):
            codes.add("SHARED_DESTINATION")
        history = email_history if channel == "email" else form_history
        if any(_key(channel, dest) == value and status != "unknown" for dest, status in history):
            codes.add("DUPLICATE_DESTINATION")
        matched = [p for p in profiles if _key("form", p.form_url) == value]
        if channel == "email":
            try:
                EMAIL.validate_python(value)  # Syntax only, never DNS/deliverability I/O.
            except ValidationError:
                codes.add("DESTINATION_INVALID")
            verified = (
                company.email.strip().casefold() == value
                and company.contact_quality_status == "verified"
            )
            verified = verified or any(
                c.email.strip().casefold() == value and c.verification_status == "verified"
                for c in contacts
            )
            if not verified:
                codes.add("EMAIL_UNVERIFIED")
        elif not matched:
            codes.add("FORM_UNANALYZED")
        else:
            profile = matched[0]
            if profile.id != profiles[0].id:
                codes.add("FORM_PROFILE_MISMATCH")
            if profile.sales_contact_status != "ALLOWED":
                codes.add("SALES_PERMISSION_UNCERTAIN")
            if profile.captcha_type != "CAPTCHA_NONE":
                codes.add("CAPTCHA")
            if profile.form_status != "READY":
                codes.add("FORM_NOT_READY")
            if not profile.delivery_supported:
                codes.add("FORM_TECHNICALLY_UNSUPPORTED")
            if (
                not profile.last_analyzed_at
                or not now - timedelta(days=7) <= profile.last_analyzed_at <= now
            ):
                codes.add("FORM_ANALYSIS_STALE")
            if not profile.fingerprint:
                codes.add("FORM_FINGERPRINT_MISSING")
            mapped = [
                dict(
                    field_type=f.field_type,
                    mapped_key=f.mapped_key,
                    confidence=f.confidence,
                    required=f.required,
                    label=f.label,
                    options=f.options,
                    recommended_value=f.recommended_value,
                    decision_source=f.decision_source,
                )
                for f in fields
                if f.form_profile_id == profile.id
            ]
            if mapping_review_reason(mapped):
                codes.add("REQUIRED_FIELD_UNKNOWN")
        rows.append(
            dict(
                type=channel,
                destination=value,
                source_url=source,
                purpose=purpose,
                status=status_for(codes),
                reasons=reason_details(codes),
                id=destination.id if destination else None,
                expected_hash=digest,
                review=review,
                core_permission=decision.status,
                execution_allowed=False,
            )
        )
    if not rows:
        lead_codes.add("CONTACT_NOT_FOUND")
        if any(
            value and not _key(channel, value)
            for channel, value in [("email", company.email), ("form", company.contact_url)]
        ):
            lead_codes.add("DESTINATION_INVALID")
    codes = lead_codes | {r["code"] for row in rows for r in row["reasons"]}
    # A prohibited candidate cannot hide behind a score; alternatives are shown
    # separately. Company-level stops dominate every destination.
    state = (
        "BLOCKED"
        if global_codes
        else next(
            (
                s
                for s in ["READY", "REVIEW", "HOLD", "BLOCKED"]
                if any(r["status"] == s for r in rows)
            ),
            status_for(lead_codes),
        )
    )
    choice = public_choice(db, company, rows, now)
    recommendation = recommend(rows)
    if choice["state"] == "CURRENT":
        recommendation["destination_selection_required"] = False
    return dict(
        company_id=company.id,
        definition_version=DEFINITION,
        evaluated_at=now,
        status=state,
        reasons=reason_details(codes),
        destinations=rows,
        **recommendation,
        human_choice=choice,
        ready_evaluation="CACHED_DESTINATION_PREPARATION_ONLY",
        dm_ready=False,
        execution_allowed=False,
        live_destination_checked=False,
        form_analysis_max_age_days=7,
    )
