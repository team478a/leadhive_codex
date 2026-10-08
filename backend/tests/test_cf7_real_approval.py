import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import form_intelligence_routes as routes
from app.models import (
    ApprovalRequest,
    OutreachAuditEvent,
    OutreachDraft,
    ProjectMember,
)
from app.services import approved_form
from app.services.cf7_static_inspection import inspect_isolated
from tests.test_cf7_real_contract_preview import page
from tests.test_form_input_preparation import inputs
from tests.test_form_input_preparation_api import setup


def candidate(auth, db, users, monkeypatch):
    profile, company = setup(auth, db, users, monkeypatch)
    observation = inputs()[2]
    observation["cf7_static"] = inspect_isolated(page(url=profile.form_url), profile.form_url, 0)
    monkeypatch.setattr(routes, "latest_live_check", lambda *args: observation)
    path = f"/api/form-profiles/{profile.id}"
    report = auth.get(path + "/input-preparation").json()
    response = auth.post(
        path + "/input-preparation/reviews",
        json={
            "expected_snapshot_hash": report["snapshot_hash"],
            "input_content_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    packet = auth.get(path + "/approval-handoff-preview").json()
    assert packet["status"] == "PREPARATION_ONLY", packet
    response = auth.post(
        path + "/approval-handoff-request", json={"expected_handoff_hash": packet["snapshot_hash"]}
    )
    assert response.status_code == 201, response.text
    return profile, company, path, packet, response.json(), observation


def approve(auth, item):
    base = f"/api/approval-requests/{item['id']}"
    expected = {"expected_hash": item["payload_hash"], "expected_version": item["payload_version"]}
    challenge = auth.post(base + "/challenge", json=expected)
    assert challenge.status_code == 200, challenge.text
    token = challenge.json()["challenge_token"]
    response = auth.post(
        base + "/challenge/verify",
        json={"challenge_token": token, "password": "test-only-long-password"},
    )
    assert response.status_code == 200, response.text
    response = auth.post(base + "/approve", json=expected | {"challenge_token": token})
    assert response.status_code == 200, response.text
    return token, expected, base, response.json()


def test_prepare_step_up_approve_idempotent_and_never_dispatch(auth, db, users, monkeypatch):
    _, company, path, packet, item, _ = candidate(auth, db, users, monkeypatch)
    assert item["delivery_method"] == "cf7_real_candidate_only" and item["status"] == "PENDING"
    again = auth.post(
        path + "/approval-handoff-request", json={"expected_handoff_hash": packet["snapshot_hash"]}
    )
    assert again.json()["id"] == item["id"]
    token, expected, base, approved = approve(auth, item)
    assert approved["approved_by_user_id"] == str(users[0].id)
    assert approved["approved_at"] and approved["approved_payload_hash"] == item["payload_hash"]
    assert approved["approved_payload_version"] == 1
    assert (
        auth.post(base + "/approve", json=expected | {"challenge_token": token}).status_code == 409
    )
    events = db.scalars(
        select(OutreachAuditEvent).where(OutreachAuditEvent.company_id == company.id)
    ).all()
    assert [e.event for e in events] == ["proposal created", "approval granted"]
    assert all("test-only" not in str(e.reason) for e in events)
    model = db.get(ApprovalRequest, item["id"])
    with pytest.raises(Exception) as error:
        approved_form.validate(db, model)
    assert getattr(error.value, "status_code", None) == 409
    for table in (
        "email_deliveries",
        "form_deliveries",
        "approved_form_dispatches",
        "approved_email_reservations",
    ):
        assert db.scalar(text("SELECT count(*) FROM " + table)) == 0
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == 1


@pytest.mark.parametrize(
    "change", ["draft", "sender", "form", "expired", "suppressed", "do_not_contact"]
)
def test_approved_candidate_revoked_or_expired_when_source_changes(
    auth, db, users, monkeypatch, change
):
    profile, company, _, _, item, observation = candidate(auth, db, users, monkeypatch)
    approve(auth, item)
    if change == "draft":
        db.scalar(
            select(OutreachDraft).where(OutreachDraft.company_id == company.id)
        ).body = "Changed"
    elif change == "sender":
        from app.models import FormSenderSettings

        db.get(FormSenderSettings, 1).email = "other@example.com"
    elif change == "form":
        observation["cf7_static"]["contract_evidence"]["dom_order"].reverse()
    elif change == "expired":
        observation["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    elif change == "suppressed":
        from app.models import SuppressionEntry

        db.add(
            SuppressionEntry(project_id=company.project_id, domain=company.domain, reason="fixture")
        )
    else:
        company.do_not_contact = True
    db.commit()
    result = auth.get(f"/api/approval-requests/{item['id']}")
    assert result.status_code == 200
    assert result.json()["status"] in {"REVOKED", "EXPIRED"}, result.text
    assert (
        db.scalar(select(OutreachAuditEvent).where(OutreachAuditEvent.event == "revoked"))
        is not None
    )


def test_human_scope_agent_denial_and_stale_hash(auth, db, users, monkeypatch):
    profile, company, path, packet, item, _ = candidate(auth, db, users, monkeypatch)
    create_path = path + "/approval-handoff-request"
    body = {"expected_handoff_hash": packet["snapshot_hash"]}
    assert auth.post(create_path, json=body | {"confirmed": True}).status_code == 422
    assert auth.post(create_path, json={"expected_handoff_hash": "0" * 64}).status_code == 409
    assert auth.post(
        create_path, json=body, headers={"Authorization": "Bearer agent"}
    ).status_code in (401, 403)
    base = f"/api/approval-requests/{item['id']}"
    expected = {"expected_hash": item["payload_hash"], "expected_version": 1}
    assert (
        auth.post(base + "/approve", json=expected | {"challenge_token": "x" * 40}).status_code
        == 403
    )
    assert (
        auth.post(
            base + "/approve", json=expected | {"challenge_token": "x" * 40, "confirmed": True}
        ).status_code
        == 422
    )
    assert (
        auth.post(base + "/challenge", json=expected | {"expected_version": 2}).status_code == 409
    )
    for action in ("approve", "reject", "revoke"):
        data = expected | (
            {"challenge_token": "x" * 40} if action == "approve" else {"reason": "fixture"}
        )
        assert auth.post(
            base + "/" + action, json=data, headers={"Authorization": "Bearer agent"}
        ).status_code in (401, 403)
    auth.post(
        "/api/auth/login", json={"email": users[1].email, "password": "test-only-long-password"}
    )
    assert auth.post(create_path, json=body).status_code == 404
    db.add(ProjectMember(project_id=company.project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.post(create_path, json=body).status_code == 404
    assert auth.post(base + "/challenge", json=expected).status_code == 404


@pytest.mark.parametrize("mutation", ["consume", "method", "wire", "expiry"])
def test_database_immutable_and_not_consumable(auth, db, users, monkeypatch, mutation):
    _, _, _, _, item, _ = candidate(auth, db, users, monkeypatch)
    statements = {
        "consume": "UPDATE approval_requests SET status='CONSUMED' WHERE id=:id",
        "method": "UPDATE approval_requests SET delivery_method='form_direct', "
        "payload_snapshot=payload_snapshot-'cf7_real_handoff' WHERE id=:id",
        "wire": "UPDATE approval_requests SET payload_snapshot=jsonb_set(payload_snapshot,"
        "'{cf7_real_handoff,snapshot,encoding,wire_sha256}','\"tampered\"') WHERE id=:id",
        "expiry": "UPDATE approval_requests SET expires_at=expires_at+interval '1 second' "
        "WHERE id=:id",
    }
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(statements[mutation]), {"id": item["id"]})
    db.expire_all()
    assert db.get(ApprovalRequest, item["id"]).status == "PENDING"


@pytest.mark.parametrize("action", ["reject", "revoke"])
def test_reject_and_revoke_audited(auth, db, users, monkeypatch, action):
    _, _, _, _, item, _ = candidate(auth, db, users, monkeypatch)
    if action == "revoke":
        approve(auth, item)
    response = auth.post(
        f"/api/approval-requests/{item['id']}/{action}",
        json={
            "expected_hash": item["payload_hash"],
            "expected_version": 1,
            "reason": "Human decision",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == {"reject": "REJECTED", "revoke": "REVOKED"}[action]


@pytest.mark.parametrize("table", ["form", "email", "delivery"])
@pytest.mark.parametrize("copied_marker", [False, True])
def test_database_execution_links_and_markers_denied(
    auth, db, users, monkeypatch, table, copied_marker
):
    from app.models import ApprovedEmailReservation, ApprovedFormDispatch, FormDelivery

    _, _, _, _, item, _ = candidate(auth, db, users, monkeypatch)
    row = db.get(ApprovalRequest, item["id"])
    payload = {"cf7_real_handoff": None} if copied_marker else {}
    approval_id = uuid4() if copied_marker else row.id
    if table == "form":
        model = ApprovedFormDispatch
        values = dict(
            id=uuid4(),
            approval_id=approval_id,
            project_id=row.project_id,
            company_id=row.company_id,
            draft_id=row.source_draft_id,
            created_by_user_id=row.created_by_user_id,
            idempotency_key=uuid4(),
            request_hash="a" * 64,
            payload_hash=row.payload_hash,
            payload_snapshot=payload,
            form_url=row.form_url,
            reason="",
            status="queued",
        )
    elif table == "email":
        model = ApprovedEmailReservation
        values = dict(
            id=uuid4(),
            approval_id=approval_id,
            batch_id=uuid4(),
            delivery_id=uuid4(),
            envelope=payload,
            envelope_hash="a" * 64,
            sender_email="sender@example.com",
            recipient_email="recipient@example.com",
        )
    else:
        model = FormDelivery
        values = dict(
            id=uuid4(),
            draft_id=row.source_draft_id,
            company_id=row.company_id,
            form_url=row.form_url,
            delivery_method="direct",
            status="pending",
            execution_authorization=payload | {"approval_id": str(approval_id)},
        )
    with pytest.raises(IntegrityError, match="cannot authorize execution"), db.begin_nested():
        db.execute(model.__table__.insert().values(**values))


def migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/0596fa531982_real_cf7_candidate_approval.py"
    )
    spec = importlib.util.spec_from_file_location("real_guard_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_preserves_history(auth, db, users, monkeypatch):
    candidate(auth, db, users, monkeypatch)
    with pytest.raises(IntegrityError, match="history prevents downgrade"), db.begin_nested():
        with Operations.context(MigrationContext.configure(db.connection())):
            migration().downgrade()
    assert db.scalar(text("SELECT to_regprocedure('cf7_real_execution_guard()')"))


def test_migration_roundtrip_empty(db):
    with db.begin_nested() as savepoint:
        with Operations.context(MigrationContext.configure(db.connection())):
            migration().downgrade()
            assert not db.scalar(text("SELECT to_regprocedure('cf7_real_execution_guard()')"))
            migration().upgrade()
            assert db.scalar(text("SELECT to_regprocedure('cf7_real_execution_guard()')"))
        savepoint.rollback()


def test_request_expiration_is_audited(auth, db, users, monkeypatch):
    from app.services import human_approval

    _, _, _, _, item, _ = candidate(auth, db, users, monkeypatch)
    future = datetime.fromisoformat(item["expires_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(human_approval, "now", lambda: future)
    result = auth.get(f"/api/approval-requests/{item['id']}")
    assert result.json()["status"] == "EXPIRED"
    assert db.scalar(select(OutreachAuditEvent).where(OutreachAuditEvent.event == "expired"))


def test_step_up_expiry_and_hash_mismatch_cannot_approve(auth, db, users, monkeypatch):
    from app.services import human_approval

    _, _, _, _, item, _ = candidate(auth, db, users, monkeypatch)
    base = f"/api/approval-requests/{item['id']}"
    expected = {"expected_hash": item["payload_hash"], "expected_version": 1}
    assert (
        auth.post(base + "/challenge", json=expected | {"expected_hash": "0" * 64}).status_code
        == 409
    )
    challenge = auth.post(base + "/challenge", json=expected).json()
    token = challenge["challenge_token"]
    assert (
        auth.post(
            base + "/challenge/verify",
            json={"challenge_token": token, "password": "test-only-long-password"},
        ).status_code
        == 200
    )
    future = datetime.fromisoformat(challenge["expires_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(human_approval, "now", lambda: future)
    result = auth.post(base + "/approve", json=expected | {"challenge_token": token})
    assert result.status_code == 403
    assert db.get(ApprovalRequest, item["id"]).status == "PENDING"
