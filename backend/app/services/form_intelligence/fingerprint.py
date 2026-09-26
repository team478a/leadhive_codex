import hashlib
import json

from app.services.form_intelligence.rules import normalize


def form_fingerprint(fields: list[dict]) -> str:
    canonical = [
        {
            "position": field["position"],
            "name": normalize(field.get("name", "")),
            "id": normalize(field.get("element_id", "")),
            "label": normalize(field.get("label", "")),
            "type": normalize(field.get("field_type", "")),
            "required": bool(field.get("required")),
            "options": [
                {
                    "value": normalize(str(option.get("value", ""))),
                    "label": normalize(str(option.get("label", ""))),
                }
                for option in field.get("options", [])
            ],
        }
        for field in fields
    ]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
