import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import ApprovalRequest, ApprovedFormDispatch, FormDelivery, OutreachDraft
from app.services import approved_form, human_approval
from tests.test_cf7_real_approval import approve, candidate


def prepared(auth, db, users, monkeypatch):
    profile, company, _, _, source, observation = candidate(auth, db, users, monkeypatch)
    _, _, _, source = approve(auth, source)
    base = f"/api/approval-requests/{source['id']}"
    preview = auth.get(base + "/cf7-reservation-preview")
    assert preview.status_code == 200, preview.text
    body = {"expected_preparation_hash": preview.json()["preparation_hash"]}
    result = auth.post(base + "/cf7-reservation-request", json=body)
    assert result.status_code == 201, result.text
    return source, result.json(), body, profile, company, observation


def reserve(auth, item, key=None):
    return auth.post(
        f"/api/approval-requests/{item['id']}/form-dispatch",
        json={
            "expected_hash": item["payload_hash"],
            "expected_version": item["payload_version"],
            "idempotency_key": str(key or uuid4()),
        },
    )


def test_separate_step_up_reservation_idempotency_and_no_execution(auth, db, users, monkeypatch):
    source, item, body, _, _, _ = prepared(auth, db, users, monkeypatch)
    assert item["id"] != source["id"] and item["status"] == "PENDING"
    assert item["cf7_reservation_plan"]["environment"] == "RESERVATION_ONLY"
    assert reserve(auth, source).status_code == 409
    assert reserve(auth, item).status_code == 409
    again = auth.post(f"/api/approval-requests/{source['id']}/cf7-reservation-request", json=body)
    assert again.json()["id"] == item["id"]
    # The original content proof cannot be reused for the new request.
    result = auth.post(
        f"/api/approval-requests/{item['id']}/approve",
        json={
            "expected_hash": item["payload_hash"],
            "expected_version": 1,
            "confirmed": True,
        },
    )
    assert result.status_code in (403, 422)
    _, _, _, item = approve(auth, item)
    key = uuid4()
    response = reserve(auth, item, key)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["reservation_only"] and not row["execution_enabled"]
    assert row["status"] == "queued" and row["started_at"] is None
    assert reserve(auth, item, key).json()["id"] == row["id"]
    assert reserve(auth, item).status_code == 409
    monkeypatch.setattr(settings, "outbound_enabled", True)
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    assert approved_form.claim(db) is None
    with pytest.raises(HTTPException):
        approved_form.validate(db, db.get(ApprovalRequest, item["id"]))
    assert db.scalar(text("SELECT count(*) FROM form_deliveries")) == 0
    assert db.scalar(text("SELECT count(*) FROM email_deliveries")) == 0
    assert auth.post(f"/api/approved-form-dispatches/{row['id']}/cancel").status_code == 200


@pytest.mark.parametrize("change", ["draft", "revoked", "expired", "suppressed"])
def test_source_change_invalidates_new_approval(auth, db, users, monkeypatch, change):
    source, item, _, _, company, _ = prepared(auth, db, users, monkeypatch)
    approve(auth, item)
    if change == "draft":
        db.scalar(
            select(OutreachDraft).where(OutreachDraft.company_id == company.id)
        ).body = "changed"
        db.commit()
    elif change == "revoked":
        assert (
            auth.post(
                f"/api/approval-requests/{source['id']}/revoke",
                json={
                    "expected_hash": source["payload_hash"],
                    "expected_version": 1,
                    "reason": "withdrawn",
                },
            ).status_code
            == 200
        )
    elif change == "expired":
        future = datetime.fromisoformat(item["expires_at"]) + timedelta(seconds=1)
        monkeypatch.setattr(human_approval, "now", lambda: future)
    else:
        from app.models import SuppressionEntry

        db.add(
            SuppressionEntry(project_id=company.project_id, domain=company.domain, reason="fixture")
        )
        db.commit()
    assert reserve(auth, item).status_code == 409
    assert auth.get(f"/api/approval-requests/{item['id']}").json()["status"] in {
        "EXPIRED",
        "REVOKED",
    }


@pytest.mark.parametrize(
    "attack", ["checking", "worker", "started", "method", "approval", "hash", "consume", "payload"]
)
def test_database_rejects_execution_and_tamper(auth, db, users, monkeypatch, attack):
    _, item, _, _, _, _ = prepared(auth, db, users, monkeypatch)
    _, _, _, item = approve(auth, item)
    result = reserve(auth, item)
    assert result.status_code == 201, result.text
    values = {
        "checking": {"status": "checking"},
        "worker": {"worker_id": uuid4()},
        "started": {"started_at": datetime.now(timezone.utc)},
        "method": {"payload_snapshot": {}},
        "approval": {"approval_id": uuid4()},
        "hash": {"payload_hash": "0" * 64},
    }
    with pytest.raises(IntegrityError), db.begin_nested():
        if attack in {"consume", "payload"}:
            update = {"status": "CONSUMED"} if attack == "consume" else {"body": "changed"}
            db.execute(
                ApprovalRequest.__table__.update()
                .where(ApprovalRequest.id == item["id"])
                .values(**update)
            )
        else:
            db.execute(
                ApprovedFormDispatch.__table__.update()
                .where(ApprovedFormDispatch.id == result.json()["id"])
                .values(**values[attack])
            )


@pytest.mark.parametrize("copied_marker", [False, True])
@pytest.mark.parametrize("table", ["delivery", "email"])
def test_delivery_link_forbidden_even_without_marker(
    auth, db, users, monkeypatch, table, copied_marker
):
    from app.models import ApprovedEmailReservation

    _, item, _, _, _, _ = prepared(auth, db, users, monkeypatch)
    row = db.get(ApprovalRequest, item["id"])
    payload = {"cf7_reservation_plan": None} if copied_marker else {"approval_id": str(row.id)}
    with pytest.raises(IntegrityError, match="cannot authorize delivery"), db.begin_nested():
        if table == "email":
            db.execute(
                ApprovedEmailReservation.__table__.insert().values(
                    id=uuid4(),
                    approval_id=uuid4() if copied_marker else row.id,
                    batch_id=uuid4(),
                    delivery_id=uuid4(),
                    envelope=payload,
                    envelope_hash="a" * 64,
                    sender_email="sender@example.com",
                    recipient_email="recipient@example.com",
                )
            )
        else:
            db.execute(
                FormDelivery.__table__.insert().values(
                    id=uuid4(),
                    draft_id=row.source_draft_id,
                    company_id=row.company_id,
                    form_url=row.form_url,
                    delivery_method="direct",
                    status="pending",
                    execution_authorization=payload,
                )
            )


def test_pending_source_and_stale_preview_denied(auth, db, users, monkeypatch):
    _, _, _, _, item, _ = candidate(auth, db, users, monkeypatch)
    base = f"/api/approval-requests/{item['id']}"
    assert auth.get(base + "/cf7-reservation-preview").status_code == 409
    approve(auth, item)
    assert (
        auth.post(
            base + "/cf7-reservation-request", json={"expected_preparation_hash": "0" * 64}
        ).status_code
        == 409
    )


def test_original_step_up_token_cannot_reapprove(auth, db, users, monkeypatch):
    _, _, _, _, source, _ = candidate(auth, db, users, monkeypatch)
    token, _, _, source = approve(auth, source)
    base = f"/api/approval-requests/{source['id']}"
    preview = auth.get(base + "/cf7-reservation-preview").json()
    item = auth.post(
        base + "/cf7-reservation-request",
        json={
            "expected_preparation_hash": preview["preparation_hash"],
        },
    ).json()
    response = auth.post(
        f"/api/approval-requests/{item['id']}/approve",
        json={
            "expected_hash": item["payload_hash"],
            "expected_version": 1,
            "challenge_token": token,
        },
    )
    assert response.status_code == 403


def test_project_viewer_and_agent_denied(auth, db, users, monkeypatch):
    from app.models import ProjectMember

    source, item, body, _, company, _ = prepared(auth, db, users, monkeypatch)
    base = f"/api/approval-requests/{source['id']}"
    assert auth.post(
        base + "/cf7-reservation-request", json=body, headers={"Authorization": "Bearer agent"}
    ).status_code in (401, 403)
    assert reserve(auth, item).status_code == 409
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.get(base + "/cf7-reservation-preview").status_code == 404
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(base + "/cf7-reservation-preview").status_code == 200
    assert auth.post(base + "/cf7-reservation-request", json=body).status_code == 404
    assert reserve(auth, item).status_code == 404


def test_ledger_and_reapproval_hash_version(auth, db, users, monkeypatch):
    from app.models import OutreachAuditEvent

    _, item, _, _, company, _ = prepared(auth, db, users, monkeypatch)
    base = f"/api/approval-requests/{item['id']}"
    expected = {"expected_hash": item["payload_hash"], "expected_version": 1}
    for mutation in ({"expected_hash": "0" * 64}, {"expected_version": 2}):
        assert auth.post(base + "/challenge", json=expected | mutation).status_code == 409
    approve(auth, item)
    assert reserve(auth, item).status_code == 201
    events = db.scalars(
        select(OutreachAuditEvent)
        .where(OutreachAuditEvent.company_id == company.id)
        .order_by(OutreachAuditEvent.timestamp)
    ).all()
    assert [e.event for e in events] == [
        "proposal created",
        "approval granted",
        "proposal created",
        "approval granted",
        "form dispatch reserved",
    ]
    assert events[0].request_id != events[2].request_id


def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/07ab219ec430_cf7_reservation_only.py"
    )
    spec = importlib.util.spec_from_file_location("cf7_reservation_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_roundtrip_empty(db):
    with db.begin_nested() as savepoint:
        with Operations.context(MigrationContext.configure(db.connection())):
            migration().downgrade()
            migration().upgrade()
        savepoint.rollback()


def test_downgrade_refuses_history(auth, db, users, monkeypatch):
    prepared(auth, db, users, monkeypatch)
    with pytest.raises(IntegrityError, match="history prevents downgrade"), db.begin_nested():
        with Operations.context(MigrationContext.configure(db.connection())):
            migration().downgrade()
