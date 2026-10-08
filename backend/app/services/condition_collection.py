"""Thin boundary between immutable conditions and existing collection execution."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select

from app.models import CollectionConditionRequest, CollectionJob, Company, LeadSourceObservation
from app.schema_collection_conditions import CollectionCondition, required_presence_plan
from app.schema_external_presence import PresenceSearchPlan
from app.services.collection_conditions import evaluate, snapshot_hash


class ConditionCollectionError(ValueError):
    """Safe public messages for a condition boundary failure."""


def binding(db, project_id, request_id, version, digest):
    row = db.get(CollectionConditionRequest, request_id)
    if row is None or row.project_id != project_id:
        raise ConditionCollectionError("条件が見つかりません。")
    if (
        row.version != version
        or row.payload_hash != digest
        or snapshot_hash(row.snapshot) != digest
    ):
        raise ConditionCollectionError(
            "条件の版・内容が一致しません。確定条件を再確認してください。"
        )
    if row.snapshot.get("collection_job_id"):
        raise ConditionCollectionError(
            "過去収集に限定した条件は、新しい条件として確定してください。"
        )
    return dict(
        request_id=str(row.id),
        version=row.version,
        payload_hash=row.payload_hash,
        snapshot=deepcopy(row.snapshot),
    )


def execution_conditions(db, job):
    frozen = job.payload.get("condition_binding")
    if "condition_binding" not in job.payload:
        return []
    if (
        not isinstance(frozen, dict)
        or not {"request_id", "version", "payload_hash", "snapshot"} <= frozen.keys()
    ):
        raise ConditionCollectionError("収集条件の整合性を確認できません。")
    try:
        request_id = UUID(frozen["request_id"])
    except (TypeError, ValueError, AttributeError) as exc:
        raise ConditionCollectionError("収集条件の整合性を確認できません。") from exc
    checked = binding(db, job.project_id, request_id, frozen["version"], frozen["payload_hash"])
    if checked != frozen:
        raise ConditionCollectionError("収集条件の整合性を確認できません。")
    return [CollectionCondition.model_validate(c) for c in frozen["snapshot"]["conditions"]]


def merged_plan(conditions, value):
    plan = PresenceSearchPlan.model_validate(value or {})
    forced = required_presence_plan(conditions).required_platforms
    return plan.model_copy(
        update={"required_platforms": sorted(set(plan.required_platforms) | set(forced))}
    )


def operation_results(db, job, offset, limit):
    conditions = execution_conditions(db, job)
    if not conditions:
        raise ConditionCollectionError("この収集には確定条件が接続されていません。")
    ids = (
        select(LeadSourceObservation.company_id)
        .join(CollectionJob, CollectionJob.id == LeadSourceObservation.collection_job_id)
        .where(CollectionJob.operation_job_id == job.id, CollectionJob.project_id == job.project_id)
    )
    query = select(Company).where(Company.project_id == job.project_id, Company.id.in_(ids))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    candidates = [
        evaluate(db, company, conditions)
        for company in db.scalars(query.order_by(Company.id).offset(offset).limit(limit))
    ]
    return dict(
        operation_id=job.id,
        status=job.status,
        condition_request_id=job.condition_request_id,
        condition_version=job.condition_version,
        condition_hash=job.payload["condition_binding"]["payload_hash"],
        total_candidates=total,
        evaluated_count=len(candidates),
        offset=offset,
        limit=limit,
        page_counts={
            s: sum(c["state"] == s for c in candidates)
            for s in ("MATCH", "NO_MATCH", "REVIEW_REQUIRED")
        },
        candidates=candidates,
        note="この収集で保存・再発見した候補だけを表示。件数はページ内集計です。"
        "収集成功件数やDM READYとは別です。",
    )
