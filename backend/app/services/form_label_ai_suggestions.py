from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company, FormLabelAiSuggestion, FormProfile, FormProfileField, Project, User
from app.services.form_intelligence.providers import (
    AmbiguousField,
    DecisionContext,
    FormDecisionProvider,
)
from app.services.form_intelligence.rules import normalize_required_label

AI_CANDIDATE_MIN_CONFIDENCE = 0.9
AI_CANDIDATE_SAMPLE_LIMIT = 20
FORBIDDEN_AI_KEYS = {"unknown", "other", "privacy_consent", "newsletter_consent"}
PHONE_KEYS = {"phone", "phone_area_code", "phone_exchange_code", "phone_line_number"}
CHOICE_KEYS = {
    "prefecture",
    "city",
    "department",
    "position",
    "contact_category",
    "contact_method",
}


@dataclass(frozen=True)
class SuggestionSamples:
    fields: list[FormProfileField]
    total_count: int


def _source_label(field: FormProfileField) -> str:
    return (field.label or field.name or "").strip()


def suggestion_samples(
    db: Session,
    project_id: UUID,
    normalized_label: str,
    field_type: str,
    *,
    limit: int = AI_CANDIDATE_SAMPLE_LIMIT,
) -> SuggestionSamples:
    normalized_label = normalize_required_label(normalized_label)
    rows = list(
        db.scalars(
            select(FormProfileField)
            .join(FormProfile, FormProfile.id == FormProfileField.form_profile_id)
            .join(Company, Company.id == FormProfile.company_id)
            .where(
                Company.project_id == project_id,
                FormProfileField.required.is_(True),
                FormProfileField.field_type == field_type,
                ~FormProfileField.decision_source.in_(("MANUAL", "POLICY")),
                (FormProfileField.mapped_key == "unknown") | (FormProfileField.confidence < 0.8),
            )
            .order_by(FormProfileField.form_profile_id, FormProfileField.position)
        ).all()
    )
    matching = [
        field
        for field in rows
        if normalize_required_label(_source_label(field)) == normalized_label
    ]
    return SuggestionSamples(fields=matching[:limit], total_count=len(matching))


def _key_matches_field_type(field_type: str, mapped_key: str) -> bool:
    if mapped_key in FORBIDDEN_AI_KEYS:
        return False
    if field_type == "textarea":
        return mapped_key == "message"
    if field_type == "email":
        return mapped_key == "email"
    if field_type == "tel":
        return mapped_key in PHONE_KEYS
    if field_type == "url":
        return mapped_key == "website"
    if field_type in {"select", "radio"}:
        return mapped_key in CHOICE_KEYS
    if field_type in {"checkbox", "hidden", "submit", "button", "reset", "image"}:
        return False
    return mapped_key not in {"message", "contact_category", "contact_method"}


def _prompt_field(field: FormProfileField, position: int) -> AmbiguousField:
    options = [
        {
            "value": str(option.get("value") or "")[:200],
            "label": str(option.get("label") or "")[:200],
        }
        for option in (field.options or [])[:50]
        if isinstance(option, dict)
    ]
    return AmbiguousField(
        position=position,
        label=(field.label or "")[:500],
        name=(field.name or "")[:500],
        field_type=field.field_type,
        required=field.required,
        options=options,
    )


def build_ai_suggestion(
    db: Session,
    project: Project,
    user: User,
    normalized_label: str,
    field_type: str,
    provider: FormDecisionProvider,
) -> FormLabelAiSuggestion:
    normalized_label = normalize_required_label(normalized_label)
    samples = suggestion_samples(db, project.id, normalized_label, field_type)
    if not samples.fields:
        raise ValueError("この項目名と型に一致する未解決の必須項目がありません。")

    prompt_fields = [_prompt_field(field, index) for index, field in enumerate(samples.fields)]
    batch = provider.decide(
        DecisionContext(
            sales_objective=project.sales_objective[:2000],
            page_text="",
            fields=prompt_fields,
        )
    )
    by_position = {decision.position: decision for decision in batch.decisions}
    accepted = []
    reason = ""
    for prompt_field in prompt_fields:
        decision = by_position.get(prompt_field.position)
        if decision is None:
            reason = "一部の例でAI候補を取得できませんでした。"
            break
        if decision.confidence < AI_CANDIDATE_MIN_CONFIDENCE:
            reason = "確信度が安全基準に達しない例がありました。"
            break
        if not _key_matches_field_type(field_type, decision.mapped_key):
            reason = "項目の型と安全に一致する候補を確認できませんでした。"
            break
        accepted.append(decision)

    mapped_keys = {decision.mapped_key for decision in accepted}
    if not reason and len(mapped_keys) != 1:
        reason = "複数の例でAIの候補が一致しませんでした。"

    status = "UNAVAILABLE" if reason else "ACTIVE"
    mapped_key = "unknown" if reason else accepted[0].mapped_key
    confidence = 0.0 if reason else min(decision.confidence for decision in accepted)
    suggestion = FormLabelAiSuggestion(
        project_id=project.id,
        normalized_label=normalized_label,
        field_type=field_type,
        suggested_mapped_key=mapped_key,
        confidence=confidence,
        sample_count=len(samples.fields),
        provider=batch.provider,
        model=str(getattr(provider, "model", settings.openai_model))[:100],
        status=status,
        reason=reason,
        usage=batch.usage,
        created_by_user_id=user.id,
    )
    db.add(suggestion)
    db.flush()
    return suggestion
