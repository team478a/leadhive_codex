from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app import worker
from app.config import settings
from app.maintenance import database_report, resume_blockers
from app.maintenance_recovery import invalidate_restored_authorizations
from app.models import (
    AgentCredential,
    AgentIdentity,
    ApplicationSettings,
    AuthSession,
    HumanApprovalProof,
    OutreachAuditEvent,
)
from app.schema_approval import Proposal
from app.services import human_approval
from tests.test_approval_foundation import workspace as workspace


def test_paused_worker_does_not_open_database_or_dispatch(monkeypatch):
    monkeypatch.setattr(settings, "worker_paused", True)

    def forbidden():
        raise AssertionError("Paused worker must not open a session")

    monkeypatch.setattr(worker, "SessionLocal", forbidden)
    assert worker.run_once() is False


def test_recovery_report_deterministic_and_read_only(db):
    first = database_report(db.connection())
    second = database_report(db.connection())
    assert first == second
    assert first["schema_revision"] == "c7a24d9e601b"
    assert "outreach_audit_events" in first["fingerprints"]
    assert "approval_requests" in first["counts"]
    assert all(len(value) == 64 for value in first["fingerprints"].values())


def test_report_detects_data_change(db):
    before = database_report(db.connection())
    db.execute(text("UPDATE target_profiles SET description = description || ' changed'"))
    after = database_report(db.connection())
    assert before["fingerprints"]["target_profiles"] != after["fingerprints"]["target_profiles"]


def test_wrong_key_is_rejected_and_secret_not_in_report(db, monkeypatch):
    key = Fernet.generate_key()
    encrypted = Fernet(key).encrypt(b"never-print-this-secret").decode()
    db.add(ApplicationSettings(id=1, serper_api_key_ciphertext=encrypted))
    db.flush()
    monkeypatch.setattr(settings, "settings_encryption_key", key.decode())
    report = database_report(db.connection())
    assert "never-print-this-secret" not in str(report)
    monkeypatch.setattr(settings, "settings_encryption_key", Fernet.generate_key().decode())
    try:
        database_report(db.connection())
    except Exception:
        pass
    else:
        raise AssertionError("Wrong encryption key was accepted")


def test_resume_report_includes_all_delivery_routes(db):
    report = resume_blockers(db.connection())
    assert set(report) == {"email", "form", "campaign", "batch", "form_operation"}
    assert all(value == 0 for value in report.values())


def test_restored_auth_invalidated_with_payload_and_approval_history_preserved(
    db, workspace, users
):
    project, company = workspace
    user_id = users[0].id
    current = datetime.now(timezone.utc)
    item = human_approval.create_proposal(
        db,
        project.id,
        Proposal(
            company_id=company.id,
            channel="email",
            delivery_method="email",
            recipient="recipient@example.com",
            subject="Restored draft",
            body="Needs renewed approval",
            sender={"name": "Owner", "email": "owner@example.com"},
        ),
        "HUMAN",
        user_id,
    )
    payload_hash, payload_version = item.payload_hash, item.payload_version
    item.status = "APPROVED"
    item.approved_by_user_id = user_id
    item.approved_at = current
    item.approved_payload_hash = payload_hash
    item.approved_payload_version = payload_version
    session = AuthSession(
        token_hash="a" * 64, user_id=user_id, expires_at=current + timedelta(hours=1)
    )
    identity = AgentIdentity(name="Restored agent", created_by_user_id=user_id)
    db.add_all([session, identity])
    db.flush()
    credential = AgentCredential(
        agent_id=identity.id,
        token_hash="b" * 64,
        scopes=["outreach:read"],
        expires_at=current + timedelta(hours=1),
    )
    proof = HumanApprovalProof(
        request_id=item.id,
        user_id=user_id,
        session_hash=session.token_hash,
        payload_hash=item.payload_hash,
        payload_version=item.payload_version,
        token_hash="c" * 64,
        expires_at=current + timedelta(minutes=5),
    )
    db.add_all([credential, proof])
    db.flush()
    original = item.payload_snapshot, item.payload_hash, item.approved_at, item.approved_by_user_id
    report = invalidate_restored_authorizations(db.connection())
    db.expire_all()
    assert report["approval_requests"] == 1
    assert item.status == "REVOKED"
    assert (
        item.payload_snapshot,
        item.payload_hash,
        item.approved_at,
        item.approved_by_user_id,
    ) == (original)
    assert session.expires_at <= datetime.now(timezone.utc)
    assert proof.expires_at <= datetime.now(timezone.utc)
    assert credential.revoked
    events = db.query(OutreachAuditEvent).filter_by(event="restored_approval_revoked").all()
    assert len(events) == 1
    assert events[0].principal_type == "SYSTEM"
    assert events[0].before_status == "APPROVED"
    assert events[0].after_status == "REVOKED"


def test_auth_invalidation_and_ledger_are_atomic(db, users, monkeypatch):
    session = AuthSession(
        token_hash="d" * 64,
        user_id=users[0].id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(session)
    db.flush()
    connection = db.connection()
    execute = connection.execute

    def fail_ledger(statement, *args, **kwargs):
        if getattr(statement, "is_insert", False):
            raise RuntimeError("ledger failure")
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(connection, "execute", fail_ledger)
    with pytest.raises(RuntimeError, match="ledger failure"):
        with connection.begin_nested():
            invalidate_restored_authorizations(connection)
    db.expire_all()
    assert session.expires_at > datetime.now(timezone.utc)
