"""Profile-owned literal review vocabulary, never search expansion or classification."""

import unicodedata

KEY = "industry_review_aliases"


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict) or len(value) > 20:
        raise ValueError("業種の別名は20業種以内で指定してください。")
    result: dict[str, list[str]] = {}
    seen: set[str] = set()
    for industry, aliases in value.items():
        if (
            not isinstance(industry, str)
            or not 2 <= len(industry.strip()) <= 100
            or any(c in industry for c in ":：,、\n\r")
            or normalize(industry) in seen
            or not isinstance(aliases, list)
            or not 1 <= len(aliases) <= 10
        ):
            raise ValueError(
                "業種名と1〜10個の別名を指定してください。同じ業種を重複登録できません。"
            )
        seen.add(normalize(industry))
        terms: list[str] = []
        for alias in aliases:
            if (
                not isinstance(alias, str)
                or not 2 <= len(alias.strip()) <= 100
                or any(c in alias for c in ":：,、\n\r")
            ):
                raise ValueError("業種の別名は2〜100文字で指定してください。")
            if normalize(alias) not in {normalize(term) for term in terms}:
                terms.append(alias.strip())
        result[industry.strip()] = terms
    return result


def terms_for(db, company, value: str) -> list[str]:
    from app.models import Project, TargetProfile

    terms = [unicodedata.normalize("NFKC", value).strip()]
    project = db.get(Project, company.project_id)
    profile = db.get(TargetProfile, project.target_profile_id) if project else None
    if (
        not profile
        or not profile.active
        or (not profile.is_system and profile.user_id != project.user_id)
    ):
        return terms
    try:
        mapping = validate(profile.scoring_rules.get(KEY, {}))
    except (ValueError, AttributeError):
        return terms  # Legacy malformed configuration never becomes evidence.
    for industry, aliases in mapping.items():
        if normalize(industry) == normalize(value):
            for alias in aliases:
                term = unicodedata.normalize("NFKC", alias).strip()
                if normalize(term) not in {normalize(item) for item in terms}:
                    terms.append(term)
    return terms
