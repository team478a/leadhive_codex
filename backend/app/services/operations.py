"""Shared operation selection logic used by APIs and background workers."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisRefreshSchedule, Company


def refresh_company_ids(db: Session, schedule: AnalysisRefreshSchedule) -> list[UUID]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=schedule.stale_days)
    return list(
        db.scalars(
            select(Company.id)
            .where(
                Company.project_id == schedule.project_id,
                Company.website_url.is_not(None),
                Company.analysis_status.notin_(("duplicate", "excluded")),
                (
                    (Company.analysis_status == "failed")
                    | Company.scraped_at.is_(None)
                    | (Company.scraped_at < cutoff)
                ),
            )
            .order_by(Company.scraped_at.asc().nullsfirst(), Company.id)
            .limit(schedule.batch_limit)
        ).all()
    )
