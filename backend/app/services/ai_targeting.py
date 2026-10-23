from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select

from app.models import Company, FormDmReadinessResult, OperationJob

AiTargetScope = Literal["eligible", "all"]


def ai_company_query(
    project_id: UUID,
    *,
    scope: AiTargetScope = "eligible",
    force: bool = False,
):
    query = select(Company).where(
        Company.project_id == project_id,
        Company.analysis_status == "completed",
    )
    if not force:
        query = query.where(Company.ai_status.in_(("pending", "failed", "skipped")))
    if scope == "all":
        return query

    latest_readiness_job_id = (
        select(OperationJob.id)
        .where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type == "form_dm_readiness",
            OperationJob.status == "completed",
        )
        .order_by(OperationJob.finished_at.desc(), OperationJob.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    form_candidate = (
        select(FormDmReadinessResult.id)
        .where(
            FormDmReadinessResult.job_id == latest_readiness_job_id,
            FormDmReadinessResult.company_id == Company.id,
            or_(
                FormDmReadinessResult.primary_reason.in_(("READY", "BROWSER_READY")),
                FormDmReadinessResult.review_queue_eligible.is_(True),
            ),
        )
        .exists()
    )
    email_candidate = func.length(func.trim(Company.email)) > 0
    return query.where(
        Company.do_not_contact.is_(False),
        Company.status != "excluded",
        or_(email_candidate, form_candidate),
    )


def ai_target_count(db, project_id: UUID, *, scope: AiTargetScope = "eligible") -> int:
    candidates = ai_company_query(project_id, scope=scope).with_only_columns(Company.id).subquery()
    return db.scalar(select(func.count()).select_from(candidates)) or 0
