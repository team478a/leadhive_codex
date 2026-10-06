"""Bounded read-only diagnostics for a fixed cohort. Never a dispatch snapshot."""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Company, TargetProfile
from app.services.completion_delivery_metrics import page_history
from app.services.dm_approval_preparation import readiness
from app.services.sales_preparation import context_hash
from app.services.sendability import DEFINITION, evaluate


def page(db, cohort, project, offset, limit, expected_context=None):
    profile = db.get(TargetProfile, project.target_profile_id)
    context = context_hash(project, profile)
    if expected_context is not None and expected_context != context:
        raise HTTPException(409, "集計中に営業条件が変わりました。最初から再集計してください。")
    if offset > len(cohort.company_ids):
        raise HTTPException(422, "集計対象の範囲外です。")
    ids = [UUID(value) for value in cohort.company_ids[offset : offset + limit]]
    companies = {
        c.id: c
        for c in db.scalars(
            select(Company).where(Company.project_id == project.id, Company.id.in_(ids))
        )
    }
    started = datetime.now(timezone.utc)
    histories = page_history(db, project.id, ids)
    rows = []
    for company_id in ids:
        company = companies.get(company_id)
        if company is None:
            rows.append(
                dict(
                    company_id=company_id,
                    delivery_funnel=histories[company_id],
                    status="HOLD",
                    dm_ready=False,
                    dm_ready_reason="削除・統合された候補",
                    destinations=[],
                    reasons=[
                        dict(
                            code="LEAD_REMOVED_OR_MERGED",
                            message="削除・統合された候補",
                            next_action="固定リストの分母は維持します。現在の対象を確認する",
                        )
                    ],
                )
            )
            continue
        result = evaluate(db, company)
        completion = readiness(db, company, project)
        rows.append(
            dict(
                company_id=company.id,
                delivery_funnel=histories[company.id],
                status=result["status"],
                dm_ready=completion["dm_ready"],
                dm_ready_reason=completion["reason"],
                reasons=result["reasons"],
                destinations=[
                    dict(
                        key=hashlib.sha256(
                            json.dumps([d["type"], d["destination"]], ensure_ascii=False).encode()
                        ).hexdigest(),
                        type=d["type"],
                        status=d["status"],
                        shared=any(r["code"] == "SHARED_DESTINATION" for r in d["reasons"]),
                    )
                    for d in result["destinations"]
                ],
            )
        )
    # Each page reads current records; across pages this is an observation interval,
    # not an immutable authorization snapshot. No data or delivery states are written.
    return dict(
        cohort_id=cohort.id,
        cohort_hash=cohort.cohort_hash,
        context_hash=context,
        definition_version=DEFINITION,
        aggregation_definition="cohort-destinations-c3-v1",
        discovered=len(cohort.company_ids),
        offset=offset,
        inspected=len(ids),
        next_offset=offset + len(ids) if offset + len(ids) < len(cohort.company_ids) else None,
        started_at=started,
        measured_at=datetime.now(timezone.utc),
        rows=rows,
        dm_ready=None,
        dm_ready_rate=None,
        execution_allowed=False,
        consistency="CURRENT_PER_PAGE_OBSERVATION_INTERVAL",
    )
