from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, Notification, OperationJob, Project, User
from app.project_access import accessible_project_condition
from app.schemas import NotificationOut
from app.security import current_user

router = APIRouter(prefix="/api")
JST = ZoneInfo("Asia/Tokyo")


def sync_notifications(db: Session, user: User) -> None:
    now = datetime.now(timezone.utc)
    overdue = db.execute(
        select(Company, Project.project_name)
        .join(Project, Project.id == Company.project_id)
        .where(
            accessible_project_condition(user.id),
            Company.next_followup_at < now,
            Company.status.in_(("target", "approached", "replied", "meeting")),
            Company.do_not_contact.is_(False),
        )
        .order_by(Company.next_followup_at)
        .limit(500)
    ).all()
    today_end = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    due_today = db.execute(
        select(Company, Project.project_name)
        .join(Project, Project.id == Company.project_id)
        .where(
            accessible_project_condition(user.id),
            Company.next_followup_at >= now,
            Company.next_followup_at < today_end,
            Company.status.in_(("target", "approached", "replied", "meeting")),
            Company.do_not_contact.is_(False),
        )
        .order_by(Company.next_followup_at)
        .limit(500)
    ).all()
    failed = db.execute(
        select(OperationJob, Project.project_name)
        .join(Project, Project.id == OperationJob.project_id)
        .where(
            accessible_project_condition(user.id),
            OperationJob.status == "failed",
            OperationJob.acknowledged_at.is_(None),
        )
        .order_by(OperationJob.created_at.desc())
        .limit(100)
    ).all()
    candidates = []
    for company, project_name in overdue:
        due_key = company.next_followup_at.isoformat()
        candidates.append(
            Notification(
                user_id=user.id,
                project_id=company.project_id,
                company_id=company.id,
                notification_type="followup_overdue",
                title=f"フォロー期限超過: {company.company_name}",
                message=f"{project_name} / 担当: {company.assignee or '未設定'}",
                dedupe_key=f"followup-overdue:{company.id}:{due_key}:{user.id}",
            )
        )
    for company, project_name in due_today:
        due_key = company.next_followup_at.isoformat()
        candidates.append(
            Notification(
                user_id=user.id,
                project_id=company.project_id,
                company_id=company.id,
                notification_type="followup_due_today",
                title=f"本日のフォロー予定: {company.company_name}",
                message=(
                    f"{project_name} / "
                    f"{company.next_followup_at.astimezone(JST).strftime('%H:%M')} "
                    f"/ 担当: {company.assignee or '未設定'}"
                ),
                dedupe_key=f"followup-today:{company.id}:{due_key}:{user.id}",
            )
        )
    for job, project_name in failed:
        candidates.append(
            Notification(
                user_id=user.id,
                project_id=job.project_id,
                operation_job_id=job.id,
                notification_type="operation_failed",
                title="バックグラウンド処理が失敗しました",
                message=f"{project_name} / {job.error_message or '処理結果を確認してください。'}",
                dedupe_key=f"operation:{job.id}:{user.id}",
            )
        )
    if not candidates:
        return
    keys = [item.dedupe_key for item in candidates]
    existing = set(
        db.scalars(select(Notification.dedupe_key).where(Notification.dedupe_key.in_(keys))).all()
    )
    db.add_all(item for item in candidates if item.dedupe_key not in existing)
    db.commit()


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    sync_notifications(db, user)
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(
        Notification.read_at.asc().nullsfirst(), Notification.created_at.desc()
    ).limit(limit)
    return db.scalars(query).all()


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if notification is None:
        raise HTTPException(404, "通知が見つかりません。")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return notification


@router.post("/notifications/read-all", status_code=204)
def read_all_notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.commit()
