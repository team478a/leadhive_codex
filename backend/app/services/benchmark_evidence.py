"""Read-only measurements of existing predicates. No correction, approval or I/O."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models import LeadSiteEvidence, LeadSourceObservation
from app.services import dm_preparation
from app.services.dm_approval_preparation import latest_preparation
from app.services.lead_enrichment import FIELDS
from app.services.lead_identity import identity_hash
from app.services.sendability import HARD, REASONS
from app.services.site_identity_review import confirmation, latest
from app.services.site_identity_review import state as identity_review_state

DEFINITION = "completion-benchmark-v1"
STAGES = [
    "DISCOVERED",
    "MATCHED",
    "IDENTITY_CONFIRMED",
    "OFFICIAL_SITE_CONFIRMED",
    "DESTINATION_FOUND",
    "CONTACT_ALLOWED",
    "SENDABILITY_READY",
    "DM_PREPARED",
    "DM_READY",
]
EXTRA = {
    "UNKNOWN": ("評価・根拠が未記録", "現在の条件に結び付く評価根拠を確認する"),
    "DESTINATION_NOT_SELECTED": ("有効な窓口選択なし", "READYの窓口をHumanが選択する"),
    "DM_NOT_PREPARED": ("根拠付きDM下書きなし", "確認した根拠から下書きを準備する"),
    "DM_PREPARATION_EXPIRED": ("DM準備の期限切れ", "根拠・窓口を再確認して再準備する"),
    "DM_PREPARATION_INVALIDATED": ("DM準備の条件変更", "条件を再確認して再準備する"),
    "DM_REVIEW_REQUIRED": ("DM入力値・送信者の確認が必要", "準備プレビューで不足を確認する"),
    "LEAD_REMOVED_OR_MERGED": ("削除・統合された候補", "固定分母を維持し現在の対象を確認する"),
}
PRIORITY = [
    "LEAD_REMOVED_OR_MERGED",
    "DO_NOT_CONTACT",
    "SUPPRESSED",
    "SALES_PROHIBITED",
    "DELIVERY_UNKNOWN",
    "DUPLICATE_DESTINATION",
    "DESTINATION_INVALID",
    "CONTACT_INVALID",
    "OFFICIAL_SITE_NOT_FOUND",
    "CONTACT_NOT_FOUND",
    "IDENTITY_UNCERTAIN",
    "SHARED_DESTINATION",
    "DESTINATION_PURPOSE_UNCERTAIN",
    "CAPTCHA",
    "FORM_UNANALYZED",
    "FORM_ANALYSIS_STALE",
    "FORM_TECHNICALLY_UNSUPPORTED",
    "REQUIRED_FIELD_UNKNOWN",
    "DESTINATION_NOT_SELECTED",
    "DM_NOT_PREPARED",
    "DM_PREPARATION_EXPIRED",
    "DM_PREPARATION_INVALIDATED",
    "DM_REVIEW_REQUIRED",
    "UNKNOWN",
]
NO_UNLOCK = HARD | {"CAPTCHA", "SHARED_DESTINATION", "UNKNOWN", "LEAD_REMOVED_OR_MERGED"}


def details(code):
    message, action = (REASONS | EXTRA).get(code, (code, "保存済み根拠を確認する"))
    return dict(code=code, message=message, next_action=action)


def pack(match, identity, site, permission, preparation, dm_ready, assessment, extra):
    codes = {r["code"] for r in assessment["reasons"]} | set(extra)
    primary = next((c for c in PRIORITY if c in codes), min(codes) if codes else None)
    raw = dict(
        zip(
            STAGES,
            [
                True,
                match,
                None if identity == "UNKNOWN" else identity == "CONFIRMED",
                None if site == "UNKNOWN" else site == "CONFIRMED",
                bool(assessment["destinations"]),
                permission == "ALLOWED",
                assessment["status"] == "READY",
                preparation == "DRAFT_PREPARED",
                dm_ready,
            ],
            strict=True,
        )
    )
    passed = {}
    previous: bool | None = True
    for code in STAGES:
        value = raw[code]
        previous = (
            False
            if previous is False or value is False
            else None
            if previous is None or value is None
            else True
        )
        passed[code] = previous
    # Counterfactual of *recorded* preparation predicates, not a forecast or send permission.
    # Alternative destinations form OR paths: unioned reasons are never treated as one AND path.
    if assessment["status"] != "READY":
        paths = [{r["code"] for r in d["reasons"]} for d in assessment["destinations"]]
        paths = paths or [{r["code"] for r in assessment["reasons"]}]
        next_stage = "SENDABILITY_READY"
    elif preparation != "DRAFT_PREPARED":
        paths = [set(extra) - {"UNKNOWN"}]
        next_stage = "DM_PREPARED"
    elif not dm_ready:
        paths = [set(extra) - {"UNKNOWN"}]
        next_stage = "DM_READY"
    else:
        paths, next_stage = [], None
    sole = sorted({next(iter(p)) for p in paths if len(p) == 1})
    unlock = [c for c in sole if c not in NO_UNLOCK and assessment["status"] != "BLOCKED"]
    return dict(
        match="UNKNOWN" if match is None else "MATCHED" if match else "NOT_MATCHED",
        identity=identity,
        official_site=site,
        permission=permission,
        preparation=preparation,
        raw_stages=raw,
        passed_stages=passed,
        primary_reason=primary,
        secondary_reasons=sorted(codes - {primary}),
        reason_codes=sorted(codes),
        extra_reasons=[details(c) for c in sorted(set(extra))],
        sole_blockers=sole,
        potential_unlock=unlock,
        next_stage=next_stage,
        execution_allowed=False,
    )


def missing(assessment):
    return pack(
        None,
        "UNKNOWN",
        "UNKNOWN",
        "UNCERTAIN",
        "NOT_STARTED",
        False,
        assessment,
        ["LEAD_REMOVED_OR_MERGED", "UNKNOWN", "DM_NOT_PREPARED"],
    )


def lead(db, company, project, assessment, completion, match):
    now = datetime.now(timezone.utc)
    human = latest(db, company.id)
    confirmation_source = (
        "HUMAN_OBSERVED"
        if identity_review_state(human, identity_hash(company), now) == "CURRENT"
        else confirmation(db, company, now)
    )
    evidence = db.scalars(
        select(LeadSiteEvidence)
        .where(
            LeadSiteEvidence.company_id == company.id,
            LeadSiteEvidence.identity_hash == identity_hash(company),
        )
        .order_by(LeadSiteEvidence.observed_at.desc(), LeadSiteEvidence.id)
    ).all()
    site = (
        "CONFIRMED"
        if company.website_url and confirmation_source == "HUMAN_OBSERVED"
        else (
            ("HIGH" if evidence[0].confidence == "CONFIRMED" else evidence[0].confidence)
            if evidence and company.website_url
            else "UNKNOWN"
            if company.website_url
            else "NOT_FOUND"
        )
    )
    identity = "CONFIRMED" if confirmation_source == "HUMAN_OBSERVED" else "UNKNOWN"
    observations = db.scalars(
        select(LeadSourceObservation)
        .where(
            LeadSourceObservation.company_id == company.id,
        )
        .order_by(LeadSourceObservation.observed_at.desc(), LeadSourceObservation.id)
    ).all()
    if identity == "UNKNOWN":
        # Exact current fact binding; a conflicting incoming observation is not evidence
        # that the existing company itself is DIFFERENT. Never derive a new CONFIRMED.
        current_facts = {f: getattr(company, f) for f in FIELDS}
        observed = next((o for o in observations if o.facts == current_facts), None)
        if observed and observed.identity_status != "CONFIRMED":
            identity = observed.identity_status
        if identity == "UNKNOWN" and human:
            identity = "REVIEW_REQUIRED"
    destination_codes = [{r["code"] for r in d["reasons"]} for d in assessment["destinations"]]
    raw_permissions = [d["core_permission"] for d in assessment["destinations"]]
    # Core stays authoritative. These stricter measurement gates never upgrade its decision.
    allowed = any(
        d["core_permission"] == "ALLOWED"
        and not (codes - {"IDENTITY_UNCERTAIN", "OFFICIAL_SITE_NOT_FOUND"})
        for d, codes in zip(assessment["destinations"], destination_codes, strict=True)
    )
    permission = (
        "PROHIBITED"
        if assessment["status"] == "BLOCKED"
        or (raw_permissions and all(p == "PROHIBITED" for p in raw_permissions))
        else "ALLOWED"
        if allowed
        else "UNCERTAIN"
    )
    row = latest_preparation(db, company.id)
    extra = []
    if match is None or identity == "UNKNOWN" or site == "UNKNOWN":
        extra.append("UNKNOWN")
    if assessment["human_choice"]["state"] != "CURRENT":
        extra.append("DESTINATION_NOT_SELECTED")
    preparation = "NOT_STARTED"
    if row is None:
        extra.append("DM_NOT_PREPARED")
    else:
        try:
            prepared = dm_preparation.public(db, company, project, row, assessment)
            preparation = (
                "DRAFT_PREPARED"
                if prepared["status"] == "DRAFT_PREPARED"
                else ("EXPIRED" if prepared["reason"] == "PREPARATION_EXPIRED" else "INVALIDATED")
            )
        except (HTTPException, ValueError, KeyError, TypeError):
            preparation = "REVIEW_REQUIRED"
        if preparation != "DRAFT_PREPARED":
            extra.append(
                {
                    "EXPIRED": "DM_PREPARATION_EXPIRED",
                    "INVALIDATED": "DM_PREPARATION_INVALIDATED",
                }.get(preparation, "DM_REVIEW_REQUIRED")
            )
        elif not completion["dm_ready"]:
            extra.append("DM_REVIEW_REQUIRED")
    result = pack(
        match, identity, site, permission, preparation, completion["dm_ready"], assessment, extra
    )
    result["confirmation_source"] = confirmation_source
    result["core_destination_permissions"] = raw_permissions
    return result
