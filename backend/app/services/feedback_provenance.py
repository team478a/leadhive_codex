"""Version-bound AI decision metadata. Activity reuse, no API keys or page text saved."""

import hashlib
import inspect
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.models import Activity, Project, TargetProfile
from app.services.ai import SYSTEM_INSTRUCTION, AnalysisDecision, rank_for_score

PREFIX = "[ai-decision-v1] "


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def binding(company) -> str:
    return digest(
        {
            "company": str(company.id),
            "project": str(company.project_id),
            "target": company.is_target,
            "website": company.website_url,
            "contact": company.contact_url,
            "model": company.ai_model,
            "analyzed_at": company.ai_analyzed_at.isoformat() if company.ai_analyzed_at else None,
        }
    )


def record_decision(db, company, context, result, provider):
    snapshot = {"target": company.is_target, "safety_blocked": True}
    event = {
        "company_id": str(company.id),
        "project_id": str(company.project_id),
        "principal": "SYSTEM",
        "prediction": company.is_target,
        "raw_ai_is_target": result.is_target,
        "score": result.score,
        "rank": company.rank,
        "binding": binding(company),
        "input_hash": digest(asdict(context)),
        "snapshot": snapshot,
        "snapshot_hash": digest(snapshot),
        "observed_at": company.ai_analyzed_at.isoformat(),
        "versions": {
            "model": provider.model,
            "prompt": digest(
                {
                    "system": SYSTEM_INSTRUCTION,
                    "schema": AnalysisDecision.model_json_schema(),
                    "ai_instruction": context.ai_instruction,
                }
            ),
            "rule": digest(
                {
                    "implementation": inspect.getsource(rank_for_score),
                    "scoring_rules": context.scoring_rules,
                }
            ),
            "code": digest(
                {
                    name: Path(__file__).with_name(name).read_text(encoding="utf-8")
                    for name in ("ai.py", "ai_analysis.py")
                }
            ),
        },
    }
    db.add(
        Activity(
            company_id=company.id,
            activity_type="note",
            note=PREFIX + json.dumps(event, ensure_ascii=False),
        )
    )


def bound_decision(db, company):
    row = db.scalar(
        select(Activity)
        .where(
            Activity.company_id == company.id,
            Activity.activity_type == "note",
            Activity.note.startswith(PREFIX),
            Activity.note.contains('"binding": "' + binding(company) + '"'),
        )
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    try:
        value = json.loads(row.note[len(PREFIX) :])
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("binding") != binding(company):
        return None
    from app.services.ai_analysis import context_for

    project = db.get(Project, company.project_id)
    profile = db.get(TargetProfile, project.target_profile_id) if project else None
    if profile is None or digest(asdict(context_for(company, project, profile))) != value.get(
        "input_hash"
    ):
        return None
    return value
