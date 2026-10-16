import hashlib
import json

from app.models import FormProfile, FormProfileField


def field_material(field: FormProfileField) -> dict:
    return {
        "id": str(field.id),
        "position": field.position,
        "selector": field.selector,
        "label": field.label,
        "name": field.name,
        "field_type": field.field_type,
        "required": field.required,
        "mapped_key": field.mapped_key,
        "confidence": field.confidence,
        "decision_source": field.decision_source,
        "recommended_value": field.recommended_value,
        "options": field.options,
        "placeholder": field.placeholder,
        "aria_label": field.aria_label,
        "surrounding_text": field.surrounding_text,
    }


def fields_hash(profile: FormProfile, fields: list[FormProfileField]) -> str:
    payload = {
        "profile_id": str(profile.id),
        "fingerprint": profile.fingerprint,
        "fields": [field_material(item) for item in fields],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
