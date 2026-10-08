"""Read-only saved checkbox evidence. Never derives selections or authorization."""

import hashlib
import json
from collections import Counter

from app.services.form_intelligence.consent import CONSENT_KEYS


def inventory(fields: list[dict], fingerprint: str) -> dict:
    candidates: dict[str, list[dict]] = {}
    counts = Counter(str(field.get("name") or "") for field in fields)
    for field in fields:
        name = str(field.get("name") or "")
        options = field.get("options")
        if field.get("field_type") == "checkbox" and (
            name.endswith("[]")
            or counts[name] > 1
            or isinstance(options, list)
            and len(options) > 1
        ):
            candidates.setdefault(name, []).append(field)
    groups = []
    for name, members in candidates.items():
        evidence = [
            {
                key: field.get(key)
                for key in (
                    "id",
                    "position",
                    "name",
                    "selector",
                    "label",
                    "required",
                    "mapped_key",
                    "options",
                )
            }
            for field in members
        ]
        binding = {"fingerprint": fingerprint, "fields": evidence}
        source_hash = hashlib.sha256(
            json.dumps(binding, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        options = []
        malformed = False
        for field in members:
            saved_options = field.get("options")
            malformed = malformed or not isinstance(saved_options, list) or not saved_options
            for index, option in enumerate(
                saved_options if isinstance(saved_options, list) else []
            ):
                if not isinstance(option, dict):
                    malformed = True
                    continue
                value = option.get("value")
                label = option.get("label")
                options.append(
                    {
                        "option_id": f"{field.get('id')}:{index}",
                        "field_id": str(field.get("id") or ""),
                        "position": field.get("position"),
                        "label": label if isinstance(label, str) else "",
                        "value": value if isinstance(value, str) else None,
                    }
                )
        values = [option["value"] for option in options]
        warnings = ["PURPOSE_AND_RULE_UNCONFIRMED", "STORED_ORDER_ONLY"]
        if not name or counts[name] != len(members):
            warnings.append("FIELD_IDENTITY_UNCERTAIN")
        if len(members) > 1:
            warnings.append("REPEATED_SAVED_FIELDS")
        if malformed or not options or any(value is None or value == "" for value in values):
            warnings.append("INCOMPLETE_OPTIONS")
        if len(values) != len(set(values)):
            warnings.append("AMBIGUOUS_VALUES")
        if any(field.get("mapped_key") in CONSENT_KEYS for field in members):
            warnings.append("CONSENT_REVIEW_REQUIRED")
        groups.append(
            {
                "group_id": hashlib.sha256(name.encode()).hexdigest(),
                "name": name,
                "label": str(members[0].get("label") or name or "名称不明"),
                "source_hash": source_hash,
                "options": options,
                "warnings": warnings,
                "required_observed": any(field.get("required") is True for field in members),
                "rule_confirmed": False,
                "selection_confirmed": False,
                "execution_allowed": False,
                "eligible_for_approval": False,
            }
        )
    source_hash = hashlib.sha256(
        json.dumps(
            {"fingerprint": fingerprint, "groups": groups}, ensure_ascii=False, sort_keys=True
        ).encode()
    ).hexdigest()
    return {
        "source": "SAVED_FIELDS",
        "source_hash": source_hash,
        "groups": groups,
        "execution_allowed": False,
        "eligible_for_approval": False,
    }
