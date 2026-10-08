"""Offline review suggestions only. Never an executable payload or authorization."""

from collections import Counter

from app.services.form_intelligence.consent import CONSENT_KEYS
from app.services.form_intelligence.fields import GROUP_REVIEW_MARKER

SENDER_KEYS = frozenset(
    {
        "company_name",
        "department",
        "position",
        "contact_name",
        "last_name",
        "first_name",
        "furigana",
        "email",
        "phone",
        "postal_code",
        "prefecture",
        "city",
        "address",
        "building",
        "website",
    }
)


def build_review_material(
    fields: list[dict], sender: dict[str, str], *, subject: str, body: str
) -> dict:
    """Suggest plain text; never infer consent or select a choice from website data."""
    names = Counter(str(field.get("name") or "") for field in fields)
    message_count = sum(field.get("mapped_key") == "message" for field in fields)
    items = []
    for field in fields:
        name = str(field.get("name") or "")
        kind = str(field.get("field_type") or "")
        key = str(field.get("mapped_key") or "unknown")
        value = None
        if name == "_wpcf7_ak_hp_textarea" or kind in {
            "hidden",
            "submit",
            "button",
            "reset",
            "image",
            "file",
        }:
            state = "DO_NOT_FILL"
        elif key in CONSENT_KEYS:
            state = "HUMAN_CONSENT_REQUIRED"
        elif GROUP_REVIEW_MARKER in str(field.get("label") or ""):
            state = "GROUP_SELECTION_REVIEW_REQUIRED"
        elif not name or names[name] > 1:
            state = "FIELD_IDENTITY_REVIEW_REQUIRED"
        elif kind in {"checkbox", "radio", "select"}:
            state = "CHOICE_REVIEW_REQUIRED"
        elif kind not in {"text", "textarea", "email", "tel", "url"}:
            state = "FIELD_REVIEW_REQUIRED"
        elif key == "message" and message_count != 1:
            state = "FIELD_IDENTITY_REVIEW_REQUIRED"
        elif key in SENDER_KEYS:
            value = str(sender.get(key) or "").strip() or None
            state = "SENDER_VALUE_PROPOSED" if value else "SENDER_VALUE_MISSING"
        elif key in {"subject", "message"}:
            value = (subject if key == "subject" else body).strip() or None
            state = "UNAPPROVED_DRAFT_VALUE" if value else "DRAFT_VALUE_MISSING"
        else:
            state = "FIELD_REVIEW_REQUIRED" if field.get("required") else "OPTIONAL_LEAVE_BLANK"
        items.append(
            {
                "position": field.get("position"),
                "name": name,
                "label": str(field.get("label") or ""),
                "field_type": kind,
                "required": bool(field.get("required")),
                "mapped_key": key,
                "options": field.get("options") or [],
                "proposed_value": value,
                "review_state": state,
            }
        )
    review_states = {
        "HUMAN_CONSENT_REQUIRED",
        "GROUP_SELECTION_REVIEW_REQUIRED",
        "FIELD_IDENTITY_REVIEW_REQUIRED",
        "CHOICE_REVIEW_REQUIRED",
        "FIELD_REVIEW_REQUIRED",
    }
    return {
        "material_version": "form-review-v1",
        "review_only": True,
        "execution_supported": False,
        "human_approved": False,
        "items": items,
        "human_review_count": sum(item["review_state"] in review_states for item in items),
        "missing_required_values": sum(
            item["required"]
            and item["review_state"] in {"SENDER_VALUE_MISSING", "DRAFT_VALUE_MISSING"}
            for item in items
        ),
    }
