"""Build and persist a reviewed browser delivery plan without visiting the target site."""

from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import func, select

from app.models import (
    Company,
    FormAnalysisLog,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    Project,
)
from app.schema_approval import Proposal
from app.services.browser_form_plan import BrowserFormFieldPlan, BrowserFormPlan, plan_hash
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_choice_groups import inventory as choice_group_inventory
from app.services.form_intelligence.consent import CONSENT_KEYS
from app.services.form_intelligence.fields import mapping_review_reason
from app.services.form_intelligence.providers import (
    AmbiguousField,
    DecisionContext,
    FormDecisionError,
    get_form_decision_provider,
)
from app.services.form_profile_delivery import sender_values, validate_sender_contact
from app.services.form_review_binding import fields_hash
from app.services.form_saved_choice_reviews import reviews as saved_choice_reviews
from app.services.human_approval import (
    company_fingerprint,
    draft_fingerprint,
    form_dependency_hash,
    form_sender_hash,
    payload_hash,
)

ALLOWED_COMPATIBILITY = {
    "",
    "CONTACT_FORM_7",
    "MULTIPART_OR_FILE",
    "JAVASCRIPT_CONFIRMATION",
    "ASYNC_SUBMISSION",
    "NO_NATIVE_SUBMIT",
    "CUSTOM_SUBMIT_HANDLER",
}


def browser_profile_eligible(db, company: Company, profile: FormProfile) -> bool:
    if (
        profile.analysis_source != "browser"
        or not profile.form_found
        or not profile.is_primary
        or profile.form_status in {"STALE", "ERROR", "BLOCKED"}
        or profile.sales_contact_status != "ALLOWED"
        or profile.captcha_type != "CAPTCHA_NONE"
        or profile.compatibility_reason_code not in ALLOWED_COMPATIBILITY
        or (not profile.delivery_supported and not profile.compatibility_reason_code)
        or profile.confirmation_page is None
        or not company.website_url
        or not profile.form_url
        or not profile.action_url
        or not _same_https_site(company.website_url, profile.form_url)
        or not _same_https_site(company.website_url, profile.action_url)
    ):
        return False
    if db.scalar(
        select(FormProfileField.id)
        .where(
            FormProfileField.form_profile_id == profile.id,
            FormProfileField.field_type == "file",
        )
        .limit(1)
    ):
        return False
    return True


def _same_https_site(source: str, target: str) -> bool:
    from urllib.parse import urlsplit

    try:
        left, right = urlsplit(source), urlsplit(target)
        return bool(
            left.scheme == right.scheme == "https"
            and left.hostname
            and right.hostname
            and left.hostname.removeprefix("www.").casefold()
            == right.hostname.removeprefix("www.").casefold()
            and left.port in (None, 443)
            and right.port in (None, 443)
            and not left.username
            and not left.password
            and not right.username
            and not right.password
        )
    except ValueError:
        return False


def _decision_log(db, profile, fingerprint, current_fields_hash):
    return db.scalar(
        select(FormAnalysisLog)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == "browser_delivery_plan_ai",
            FormAnalysisLog.details["profile_fingerprint"].astext == fingerprint,
            FormAnalysisLog.details["fields_hash"].astext == current_fields_hash,
        )
        .order_by(FormAnalysisLog.created_at.desc(), FormAnalysisLog.id.desc())
        .limit(1)
    )


def _ai_mapping_suggestions(db, company, profile, fields, *, allow_request=True):
    unknown = [
        field
        for field in fields
        if field.field_type not in {"hidden", "submit", "button", "reset", "image"}
        and field.mapped_key == "unknown"
    ]
    if not unknown:
        return {}
    current_hash = fields_hash(profile, fields)
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(profile.id), 0))))
    previous = _decision_log(db, profile, profile.fingerprint, current_hash)
    if previous:
        return previous.details.get("decisions", {})
    if not allow_request:
        return {}

    provider = get_form_decision_provider()
    decisions = {}
    provider_name = provider.name if provider else "unavailable"
    duration_ms = 0
    details = {
        "operation": "browser_delivery_plan_ai",
        "profile_fingerprint": profile.fingerprint,
        "fields_hash": current_hash,
        "attempted": True,
        "decisions": decisions,
    }
    event_type = "analysis_failed"
    if provider:
        project = db.get(Project, company.project_id)
        try:
            batch = provider.decide(
                DecisionContext(
                    sales_objective=project.sales_objective if project else "",
                    page_text="",
                    fields=[
                        AmbiguousField(
                            position=field.position,
                            label=field.label,
                            name=field.name,
                            field_type=field.field_type,
                            required=field.required,
                            options=field.options or [],
                        )
                        for field in unknown
                    ],
                )
            )
            valid_positions = {field.position for field in unknown}
            for suggestion in batch.decisions:
                if suggestion.position not in valid_positions:
                    continue
                field = next(item for item in unknown if item.position == suggestion.position)
                if suggestion.mapped_key != "unknown" and suggestion.confidence >= 0.8:
                    decisions[str(field.id)] = {
                        "mapped_key": suggestion.mapped_key,
                        "confidence": suggestion.confidence,
                        "recommended_value": suggestion.recommended_value[:500],
                    }
            provider_name = batch.provider
            duration_ms = batch.duration_ms
            event_type = "ai_decision_completed"
            details["decisions"] = decisions
            details["success"] = True
        except Exception as exc:
            details["error"] = (
                str(exc)[:300] if isinstance(exc, FormDecisionError) else "AI suggestion failed"
            )
            details["success"] = False
    else:
        details["success"] = False
        details["error"] = "AI provider unavailable"
    db.add(
        FormAnalysisLog(
            company_id=company.id,
            form_profile_id=profile.id,
            event_type=event_type,
            provider=provider_name,
            duration_ms=duration_ms,
            details=details,
        )
    )
    db.flush()
    return decisions


def _current_review_confirmed(db, profile, fields):
    current_hash = fields_hash(profile, fields)
    return db.scalar(
        select(FormAnalysisLog.id)
        .where(
            FormAnalysisLog.form_profile_id == profile.id,
            FormAnalysisLog.details["operation"].astext == "form_review_confirmed",
            FormAnalysisLog.details["profile_fingerprint"].astext == profile.fingerprint,
            FormAnalysisLog.details["fields_hash"].astext == current_hash,
            FormAnalysisLog.details["confirmed_no_sales_prohibition"].astext == "true",
        )
        .limit(1)
    )


def preparation(db, company: Company, draft: OutreachDraft, *, allow_ai_suggestion=True):
    if draft.channel != "form" or draft.company_id != company.id:
        raise HTTPException(409, "フォーム用Draftを選択してください。")
    profile = db.scalar(
        select(FormProfile)
        .where(FormProfile.company_id == company.id)
        .order_by(FormProfile.is_primary.desc(), FormProfile.updated_at.desc(), FormProfile.id)
        .limit(1)
    )
    if not profile or not browser_profile_eligible(db, company, profile):
        raise HTTPException(409, "ブラウザー送信の対象条件を満たしません。")
    if not profile.fingerprint or len(profile.fingerprint) != 64:
        raise HTTPException(409, "フォーム構造が未確定です。再解析してください。")
    permission = evaluate_contact_permission(
        db,
        company.project_id,
        company.id,
        "form",
        profile.form_url,
        allow_browser_review_required=True,
    )
    if not permission.allowed or company.do_not_contact:
        raise HTTPException(409, permission.message or "連絡禁止のため準備できません。")
    fields = list(
        db.scalars(
            select(FormProfileField)
            .where(FormProfileField.form_profile_id == profile.id)
            .order_by(FormProfileField.position, FormProfileField.id)
        ).all()
    )
    if not fields or any(field.field_type == "file" for field in fields):
        raise HTTPException(409, "入力項目がない、またはファイル添付欄があります。")
    if len({field.name for field in fields if field.name}) != len(
        [field for field in fields if field.name]
    ):
        raise HTTPException(409, "同名の入力項目があるため準備できません。")
    if any(
        field.field_type not in {"hidden", "submit", "button", "reset", "image"}
        and (not field.name or not field.selector)
        for field in fields
    ):
        raise HTTPException(409, "入力項目の識別情報が不足しています。")
    if not _current_review_confirmed(db, profile, fields):
        raise HTTPException(409, "フォーム確認キューで内容を確定してください。")

    suggestions = _ai_mapping_suggestions(
        db, company, profile, fields, allow_request=allow_ai_suggestion
    )
    mapped = []
    for field in fields:
        suggestion = suggestions.get(str(field.id), {})
        mapped_key = suggestion.get("mapped_key", field.mapped_key)
        confidence = suggestion.get("confidence", field.confidence)
        recommended_value = suggestion.get("recommended_value", field.recommended_value)
        mapped.append(
            {
                "field": field,
                "mapped_key": mapped_key,
                "confidence": confidence,
                "recommended_value": recommended_value,
            }
        )
    mapping_reason = mapping_review_reason(
        [
            {
                "field_type": row["field"].field_type,
                "mapped_key": row["mapped_key"],
                "confidence": row["confidence"],
                "required": row["field"].required,
                "label": row["field"].label,
                "options": row["field"].options or [],
                "recommended_value": row["recommended_value"],
                "decision_source": "OPENAI"
                if row["field"].mapped_key == "unknown" and row["mapped_key"] != "unknown"
                else row["field"].decision_source,
            }
            for row in mapped
        ]
    )
    if mapping_reason:
        raise HTTPException(409, mapping_reason)
    choice_groups = choice_group_inventory(db, profile)
    if any(
        group.get("review_status") != "RECORDED"
        or not group.get("review_supported")
        or not group.get("permanent_review")
        for group in choice_groups
    ):
        raise HTTPException(
            409, "選択肢の確認が不足しています。フォーム確認キューを確認してください。"
        )
    saved_groups = saved_choice_reviews(db, profile)
    if any(not group.get("review_current") for group in saved_groups):
        raise HTTPException(
            409,
            "保存済み選択肢の確認が不足しています。フォーム確認キューを確認してください。",
        )

    sender_sources = sender_values(db.get(FormSenderSettings, 1))
    try:
        validate_sender_contact(
            [
                SimpleNamespace(
                    mapped_key=row["mapped_key"],
                    field_type=row["field"].field_type,
                    required=row["field"].required,
                    options=row["field"].options,
                    recommended_value=row["recommended_value"],
                    decision_source=(
                        "OPENAI"
                        if row["field"].mapped_key == "unknown" and row["mapped_key"] != "unknown"
                        else row["field"].decision_source
                    ),
                )
                for row in mapped
            ],
            sender_sources,
        )
    except Exception as exc:
        message = getattr(exc, "public_message", str(exc))
        raise HTTPException(409, message) from exc
    values_source = sender_sources | {"subject": draft.subject, "message": draft.body}
    field_values = {}
    plan_fields = []
    for row in mapped:
        field = row["field"]
        if field.field_type in {"hidden", "submit", "button", "reset", "image"}:
            continue
        mapped_key = row["mapped_key"]
        value = values_source.get(mapped_key, "") or row["recommended_value"]
        if mapped_key in CONSENT_KEYS and row["field"].decision_source != "MANUAL":
            value = ""
        if field.required and not str(value).strip():
            raise HTTPException(409, "必須項目の入力値が不足しています。")
        value_limit = 30000 if mapped_key == "message" else 2000
        value = str(value)[:value_limit]
        field_values[field.name] = value
        plan_fields.append(
            BrowserFormFieldPlan(
                profile_field_id=field.id,
                selector=field.selector,
                name=field.name,
                field_type=field.field_type,
                mapped_key=mapped_key,
                value=value,
                required=field.required,
            )
        )
    if not any(row["mapped_key"] == "message" for row in mapped):
        raise HTTPException(409, "営業文面の入力先が確認できません。")
    kind = {
        "CONTACT_FORM_7": "contact_form_7",
        "MULTIPART_OR_FILE": "multipart",
        "JAVASCRIPT_CONFIRMATION": "javascript",
        "ASYNC_SUBMISSION": "javascript",
        "NO_NATIVE_SUBMIT": "javascript",
        "CUSTOM_SUBMIT_HANDLER": "javascript",
    }.get(profile.compatibility_reason_code, "native")
    form_url = str(TypeAdapter(HttpUrl).validate_python(profile.form_url))
    action_url = str(TypeAdapter(HttpUrl).validate_python(profile.action_url))
    try:
        plan = BrowserFormPlan(
            project_id=company.project_id,
            company_id=company.id,
            source_draft_id=draft.id,
            form_profile_id=profile.id,
            form_fingerprint=profile.fingerprint,
            form_url=form_url,
            action_url=action_url,
            form_index=profile.form_index,
            confirmation_expected=profile.confirmation_page is True,
            submission_kind=kind,
            fields=tuple(plan_fields),
        )
        proposal = Proposal(
            company_id=company.id,
            channel="form",
            delivery_method="browser_form",
            source_draft_id=draft.id,
            form_url=form_url,
            form_action_url=action_url,
            subject=draft.subject,
            body=draft.body,
            sender={
                "name": sender_sources.get("contact_name", ""),
                "email": sender_sources.get("email", ""),
                "company": sender_sources.get("company_name", ""),
                "phone": sender_sources.get("phone", ""),
            },
            field_values=field_values,
            browser_form_plan=plan,
        )
    except ValueError as exc:
        raise HTTPException(409, "保存済みのフォーム構造が計画条件に合いません。") from exc
    digest = payload_hash(
        {
            "proposal": proposal.model_dump(mode="json"),
            "company": company_fingerprint(company),
            "draft": draft_fingerprint(draft),
            "form": form_dependency_hash(db, company.id),
            "sender": form_sender_hash(db),
            "browser_form_plan_hash": plan_hash(plan),
        }
    )
    return proposal, {
        "preparation_hash": digest,
        "company_name": company.company_name,
        "form_profile_id": str(profile.id),
        "form_fingerprint": profile.fingerprint,
        "browser_form_plan_hash": plan_hash(plan),
        "proposal": proposal.model_dump(mode="json"),
        "fields": [
            {
                "name": row.name,
                "label": next(field.label for field in fields if field.id == row.profile_field_id),
                "required": row.required,
                "value": row.value,
            }
            for row in plan_fields
        ],
    }
