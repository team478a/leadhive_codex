"""Industry-independent context hints, never facts or permission decisions."""

import re
from urllib.parse import urlsplit

CONTEXT_TERMS = {
    "PROVISION_CONTEXT": (
        "提供",
        "受託",
        "代行",
        "ご依頼",
        "料金",
        "お任せ",
        "ご相談",
        "お客様",
        "クライアント",
        "法人向け",
        "企業向け",
        "企業・団体",
    ),
    "SELF_USE_CONTEXT": ("自社で利用", "当社で利用", "運用ポリシー", "運用規約"),
    "EDUCATION_CONTEXT": ("コース", "授業", "受講", "学習", "スクール"),
    "MEDIA_CONTEXT": ("おすすめ", "ランキング", "まとめ", "ブログ", "マガジン", "記事"),
}


def context_hint(text: str, source_url: str, matched_term: str) -> dict:
    host = (urlsplit(source_url).hostname or "").lower().rstrip(".")
    contexts = []
    if host.endswith((".lg.jp", ".go.jp")):
        contexts.append("PUBLIC_ORGANIZATION_CONTEXT")
    for kind, terms in CONTEXT_TERMS.items():
        if any(term in text for term in terms):
            contexts.append(kind)
    literal = re.escape(matched_term)
    if re.search(rf"(?:株式会社|有限会社|合同会社)\s*{literal}|{literal}\s*株式会社", text):
        contexts.append("COMPANY_NAME_CONTEXT")
    return dict(
        status="CONTEXT_FOUND" if contexts else "ROLE_UNRESOLVED",
        contexts=contexts,
        confirmed=False,
        reason="ROLE_REQUIRES_HUMAN_REVIEW",
    )


def hint_order(excerpt: dict) -> int:
    contexts = excerpt["role_hint"]["contexts"]
    # Mixed/negative context is retained for review, never discarded or marked NO_MATCH.
    return 0 if contexts == ["PROVISION_CONTEXT"] else 1
