"""Bounded text templates, not an AI command interpreter or a collection runner."""

import re
import unicodedata

from app.schema_collection_conditions import CollectionCondition

MEDIA = {
    "instagram": "INSTAGRAM",
    "インスタグラム": "INSTAGRAM",
    "インスタ": "INSTAGRAM",
    "x": "X",
    "twitter": "X",
    "facebook": "FACEBOOK",
    "youtube": "YOUTUBE",
    "tiktok": "TIKTOK",
    "hotpepper": "HOTPEPPER",
    "ホットペッパー": "HOTPEPPER",
    "hotpepper beauty": "HOTPEPPER_BEAUTY",
    "ホットペッパービューティー": "HOTPEPPER_BEAUTY",
    "食べログ": "TABELOG",
    "indeed": "INDEED",
    "求人ボックス": "KYUJIN_BOX",
    "ぐるなび": "GURUNAVI",
    "epark": "EPARK",
    "楽天ビューティー": "RAKUTEN_BEAUTY",
}


def propose(text):
    normalized = unicodedata.normalize("NFKC", text).strip()
    clauses = [s.strip() for s in re.split(r"[\n、。;]+", normalized) if s.strip()]
    expanded = []
    for clause in clauses:
        match = re.fullmatch(r"([^:]+?(?:市|区|町|村))の([^で:]+)で(.+)", clause)
        if match:
            expanded.extend([f"地域:{match[1]}", f"業種:{match[2]}", match[3]])
        else:
            expanded.append(clause)
    if not expanded or len(expanded) > 20 or any(len(s) > 300 for s in expanded):
        raise ValueError("条件は20項目以内、1項目300文字以内に分けて入力してください。")
    rows, warnings, seen = [], [], set()
    for index, clause in enumerate(expanded):
        priority, content = "MUST", clause
        prefix = re.match(r"^(必須|希望|除外|MUST|WANT|EXCLUDE)\s*[:：]\s*(.+)$", clause, re.I)
        if prefix:
            priority = {"必須": "MUST", "希望": "WANT", "除外": "EXCLUDE"}.get(
                prefix[1], prefix[1].upper()
            )
            content = prefix[2].strip()
        kind, operator, value = "UNRESOLVED", "EQUALS", clause
        field = re.fullmatch(r"(地域|業種)\s*:\s*(.+)", content)
        if field and not re.search(r"または|もしくは|かつ|\bOR\b|\bAND\b", field[2], re.I):
            kind, value = ("AREA" if field[1] == "地域" else "INDUSTRY"), field[2].strip()
        else:
            existence = re.fullmatch(
                r"(.+?)(?:が)?(あり|ある|なし|ない|掲載あり|掲載なし)", content
            )
            if existence:
                label = existence[1].strip().casefold()
                platform = MEDIA.get(label)
                if label == "公式サイト":
                    platform = "OFFICIAL_SITE"
                negative = existence[2] in {"なし", "ない", "掲載なし"}
                if platform and (not negative or priority == "MUST"):
                    kind = "OFFICIAL_SITE" if platform == "OFFICIAL_SITE" else "MEDIA_EXISTS"
                    operator, value = "EXISTS", platform
                    if negative:
                        priority = "EXCLUDE"
        key = (kind, operator, value)
        if key in seen:
            kind, operator, value = "UNRESOLVED", "EQUALS", f"重複・矛盾の確認:{clause}"
        if kind == "UNRESOLVED":
            warnings.append(
                f"「{clause}」は自動解釈できません。内容・種類・優先度を確認してください。"
            )
        else:
            seen.add(key)
        rows.append(
            CollectionCondition.model_validate(
                dict(
                    id=f"proposal-{index + 1}",
                    priority=priority,
                    type=kind,
                    operator=operator,
                    value=value,
                )
            ).model_dump()
        )
    regions = [c["value"] for c in rows if c["type"] == "AREA" and c["priority"] == "MUST"]
    industries = [c["value"] for c in rows if c["type"] == "INDUSTRY" and c["priority"] == "MUST"]
    return dict(
        conditions=rows,
        warnings=warnings,
        original_request=text,
        suggested_region=regions[0] if len(regions) == 1 else None,
        suggested_keywords=industries if len(industries) == 1 else [],
        confirmation_required=True,
        collection_started=False,
        parser_version="bounded-templates-v1",
    )
