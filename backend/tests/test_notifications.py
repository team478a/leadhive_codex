from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import Company, Notification, OperationJob

JST = ZoneInfo("Asia/Tokyo")


def make_project(auth):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    return auth.post(
        "/api/projects",
        json={
            "project_name": "通知テスト",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "全国",
            "status": "active",
        },
    ).json()


def test_notifications_are_deduplicated_and_can_be_read(auth, users, db):
    project = make_project(auth)
    now = datetime.now(timezone.utc)
    company = Company(
        project_id=UUID(project["id"]),
        company_name="Notify",
        website_url="https://notify.example",
        domain="notify.example",
        email="info@notify.example",
        source="url",
        status="target",
        assignee="佐藤",
        next_followup_at=now - timedelta(hours=2),
    )
    db.add(company)
    due_today = Company(
        project_id=UUID(project["id"]),
        company_name="Due today",
        website_url="https://due-today.example",
        domain="due-today.example",
        email="info@due-today.example",
        source="url",
        status="replied",
        next_followup_at=(
            now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1, hours=-1)
        ),
    )
    db.add(due_today)
    operation = OperationJob(
        project_id=company.project_id,
        operation_type="web_analysis",
        status="failed",
        error_message="解析に失敗しました。",
    )
    db.add(operation)
    db.commit()

    first = auth.get("/api/notifications").json()
    assert {item["notification_type"] for item in first} == {
        "followup_overdue",
        "followup_due_today",
        "operation_failed",
    }
    assert all(item["read_at"] is None for item in first)
    assert len(auth.get("/api/notifications").json()) == 3
    assert db.scalar(select(Notification).where(Notification.user_id == users[0].id)) is not None

    marked = auth.post(f"/api/notifications/{first[0]['id']}/read")
    assert marked.status_code == 200 and marked.json()["read_at"] is not None
    assert len(auth.get("/api/notifications", params={"unread_only": True}).json()) == 2
    assert auth.post("/api/notifications/read-all").status_code == 204
    assert auth.get("/api/notifications", params={"unread_only": True}).json() == []

    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.post(f"/api/notifications/{first[0]['id']}/read").status_code == 404
    assert auth.get("/api/notifications").json() == []
