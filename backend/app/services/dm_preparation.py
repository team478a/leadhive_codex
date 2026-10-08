"""Deterministic template + Human-observed facts. No external calls or dispatch."""

import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models import LeadDmPreparation, OutreachTemplate, TargetProfile
from app.services.destination_choice import latest
from app.services.sales_preparation import context_hash
from app.services.sendability import evaluate
from app.services.site_identity_review import official_evidence_url


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def template_hash(template):
    return digest(
        [str(template.id), template.name, template.channel, template.subject, template.body]
    )


def context(db, project):
    profile = db.get(TargetProfile, project.target_profile_id)
    if profile is None:
        raise HTTPException(409, "ターゲット条件が見つかりません。")
    return context_hash(project, profile)


def render(template, company, fact):
    if template.body.count("{{personalization}}") != 1:
        raise HTTPException(422, "本文に{{personalization}}を1つ指定してください。")
    for value in [template.subject, template.body]:
        for token in re.findall(r"{{.*?}}", value, flags=re.DOTALL):
            if token not in {"{{company_name}}", "{{personalization}}"}:
                raise HTTPException(
                    422, "利用できる差し込みはcompany_nameとpersonalizationだけです。"
                )
    for value in [template.subject, template.body]:
        remaining = re.sub(r"{{company_name}}|{{personalization}}", "", value)
        if "{{" in remaining or "}}" in remaining:
            raise HTTPException(422, "差し込みの記法を確認してください。")
    if "{{personalization}}" in template.subject:
        raise HTTPException(422, "個別の一文は本文に指定してください。")
    # One pass: source values are data, never recursively expanded or interpreted.
    replacements = {
        "{{company_name}}": company.company_name,
        "{{personalization}}": f"公開情報で「{fact}」を拝見しました。",
    }

    def expand(value):
        return re.sub(
            r"{{company_name}}|{{personalization}}", lambda m: replacements[m.group()], value
        )

    subject = expand(template.subject) if template.channel == "email" else ""
    body = expand(template.body)
    if (
        (template.channel == "email" and not subject.strip())
        or len(subject) > 300
        or "\n" in subject
        or "\r" in subject
        or len(body) > 10000
    ):
        raise HTTPException(422, "件名または本文の長さを確認してください。")
    return subject, body


def prepare(db, company, project, user, body):
    result = evaluate(db, company)
    choice = result["human_choice"]
    if choice["state"] != "CURRENT" or choice["version"] != body.expected_choice_version:
        raise HTTPException(409, "有効な窓口選択を再確認してください。")
    selected = choice["active_destination"]
    template = db.get(OutreachTemplate, body.template_id)
    if template is None or template.project_id != project.id:
        raise HTTPException(404, "テンプレートが見つかりません。")
    if (
        template.channel != selected["type"]
        or template_hash(template) != body.expected_template_hash
        or context(db, project) != body.expected_context_hash
        or selected["payload_hash"] != body.expected_destination_hash
    ):
        raise HTTPException(409, "窓口・テンプレート・営業条件が変わりました。再読込してください。")
    try:
        source = official_evidence_url(company, body.source_url)
    except ValueError as exc:
        raise HTTPException(422, "根拠URLは公式サイト内の公開ページを指定してください。") from exc
    if body.fact not in body.evidence_excerpt:
        raise HTTPException(422, "個別化に使う事実は、確認した公開情報の引用に含めてください。")
    subject, text = render(template, company, body.fact)
    choice_row = latest(db, company.id)
    now = datetime.now(timezone.utc)
    if choice_row.expires_at <= now:
        raise HTTPException(409, "窓口選択の期限が切れました。")
    row = LeadDmPreparation(
        project_id=project.id,
        company_id=company.id,
        actor_user_id=user.id,
        choice_id=choice_row.id,
        choice_version=choice_row.version,
        template_id=template.id,
        template_hash=template_hash(template),
        context_hash=context(db, project),
        created_at=now,
        expires_at=choice_row.expires_at,
        snapshot=dict(
            version="dm-template-evidence-v1",
            company_name=company.company_name,
            destination={k: str(v) for k, v in selected.items()},
            template=dict(name=template.name, subject=template.subject, body=template.body),
            subject=subject,
            body=text,
            evidence=dict(
                source_url=source,
                fact=body.fact,
                evidence_excerpt=body.evidence_excerpt,
                observed_at=now.isoformat(),
                confidence="HUMAN_OBSERVED",
                verified_by_user_id=str(user.id),
            ),
        ),
    )
    db.add(row)
    db.commit()
    return public(db, company, project, row, result)


def public(db, company, project, row, assessment=None):
    assessment = assessment or evaluate(db, company)
    choice = assessment["human_choice"]
    template = db.get(OutreachTemplate, row.template_id)
    reason = None
    if row.expires_at <= datetime.now(timezone.utc):
        reason = "PREPARATION_EXPIRED"
    elif choice["state"] != "CURRENT" or choice["version"] != row.choice_version:
        reason = "DESTINATION_CHOICE_CHANGED"
    elif (
        choice["active_destination"]["payload_hash"] != row.snapshot["destination"]["payload_hash"]
    ):
        reason = "DESTINATION_CHANGED"
    elif context(db, project) != row.context_hash:
        reason = "SALES_CONTEXT_CHANGED"
    elif template is None or template_hash(template) != row.template_hash:
        reason = "TEMPLATE_CHANGED"
    return dict(
        id=row.id,
        status="REVIEW" if reason else "DRAFT_PREPARED",
        reason=reason,
        choice_version=row.choice_version,
        created_at=row.created_at,
        expires_at=row.expires_at,
        prepared_by_user_id=row.actor_user_id,
        snapshot=row.snapshot,
        dm_ready=False,
        execution_allowed=False,
    )


def list_preparations(db, company, project):
    result = evaluate(db, company)
    rows = db.scalars(
        select(LeadDmPreparation)
        .where(LeadDmPreparation.company_id == company.id)
        .order_by(LeadDmPreparation.created_at.desc(), LeadDmPreparation.id.desc())
        .limit(10)
    ).all()
    return [public(db, company, project, row, result) for row in rows]
