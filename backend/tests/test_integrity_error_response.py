import asyncio
import json
from types import SimpleNamespace

from fastapi import Request
from sqlalchemy.exc import IntegrityError

from app.main import conflict_error


def make_request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/test", "headers": []})


def test_check_violation_reports_schema_update_message():
    original = SimpleNamespace(
        sqlstate="23514",
        diag=SimpleNamespace(constraint_name="ck_operation_job_type"),
    )
    response = asyncio.run(conflict_error(make_request(), IntegrityError("", {}, original)))
    assert response.status_code == 409
    assert json.loads(response.body) == {
        "detail": "データベースの更新が未完了です。管理者に連絡してください。"
    }


def test_unique_violation_keeps_existing_conflict_message():
    original = SimpleNamespace(
        sqlstate="23505",
        diag=SimpleNamespace(constraint_name="uq_active_operation"),
    )
    response = asyncio.run(conflict_error(make_request(), IntegrityError("", {}, original)))
    assert response.status_code == 409
    assert json.loads(response.body) == {"detail": "関連データと競合しています。"}
