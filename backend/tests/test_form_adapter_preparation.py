from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    EmailDelivery,
    FormDelivery,
    FormDispatchSite,
    HumanApprovalProof,
    OutreachAuditEvent,
    ProjectMember,
)
from app.services import approved_form, human_approval
from tests.test_approval_foundation import agent_token, approve, challenge, expected
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


@pytest.fixture
def adapter_source(form_source, db, monkeypatch):
    monkeypatch.setattr(settings, "form_adapter_preparation_enabled", True)
    form_source[1].contact_url = "https://fixture.example/contact"
    form_source[3].form_url = "https://fixture.example/contact"
    form_source[3].action_url = "https://fixture.example/submit"
    db.commit()
    return form_source


def preview(auth, source):
    result = auth.get(f"/api/outreach-drafts/{source[2].id}/form-adapter-preview")
    assert result.status_code == 200, result.text
    return result.json()


def prepare(auth, source):
    result = auth.post(
        f"/api/outreach-drafts/{source[2].id}/form-adapter-request",
        json={"expected_preparation_hash": preview(auth, source)["preparation_hash"]},
    )
    assert result.status_code == 201, result.text
    return result.json()


def reserve(auth, item, key=None):
    return auth.post(
        f"/api/approval-requests/{item['id']}/form-dispatch",
        json=expected(item) | {"idempotency_key": str(key or uuid4())},
    )


def test_end_to_end_approval_reservation_without_execution(auth, adapter_source, db, monkeypatch):
    item = prepare(auth, adapter_source)
    assert item["status"] == "PENDING" and item["adapter_plan_hash"]
    assert reserve(auth, item).status_code == 409
    assert approve(auth, item, "x" * 43).status_code == 403
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    proof = db.scalar(select(HumanApprovalProof).where(HumanApprovalProof.request_id == item["id"]))
    assert proof.payload_hash == item["payload_hash"] and proof.payload_version == 1
    key = uuid4()
    result = reserve(auth, item, key)
    assert result.status_code == 201, result.text
    row = result.json()
    assert row["status"] == "queued" and row["reservation_only"] and not row["execution_enabled"]
    assert row["payload_snapshot"] == item["payload_snapshot"]
    assert reserve(auth, item, key).json()["id"] == row["id"]
    assert reserve(auth, item).status_code == 409
    assert (
        db.scalar(
            select(FormDispatchSite.site_key).where(FormDispatchSite.dispatch_id == row["id"])
        )
        == "fixture.example"
    )
    monkeypatch.setattr(settings, "outbound_enabled", True)
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    assert approved_form.claim(db) is None
    listed = auth.get(f"/api/projects/{adapter_source[0].id}/approved-form-dispatches").json()
    assert listed[0]["reservation_only"] and not listed[0]["execution_enabled"]
    assert db.get(ApprovalRequest, item["id"]).status == "APPROVED"
    for model in (FormDelivery, EmailDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    events = db.scalars(
        select(OutreachAuditEvent.event).where(OutreachAuditEvent.request_id == item["id"])
    ).all()
    assert {"proposal created", "approval granted", "form dispatch reserved"} <= set(events)


@pytest.mark.parametrize("change", ["off", "production", "real_url", "captcha", "permission"])
def test_fail_closed_preparation(auth, adapter_source, db, monkeypatch, change):
    if change == "off":
        monkeypatch.setattr(settings, "form_adapter_preparation_enabled", False)
    elif change == "production":
        monkeypatch.setattr(
            settings, "database_url", "postgresql+psycopg://x:x@localhost/production"
        )
    elif change == "real_url":
        adapter_source[3].action_url = "https://real.example/submit"
    elif change == "captcha":
        adapter_source[3].captcha_type = "CAPTCHA_RECAPTCHA"
    else:
        adapter_source[3].sales_contact_status = "PROHIBITED"
    db.commit()
    assert (
        auth.get(f"/api/outreach-drafts/{adapter_source[2].id}/form-adapter-preview").status_code
        == 409
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.project_id == adapter_source[0].id)
        )
        == 0
    )


def test_default_flag():
    from app.config import Settings

    assert Settings.model_fields["form_adapter_preparation_enabled"].default is False


def test_no_caller_plan_or_generic_adapter_proposal(auth, adapter_source):
    seen = preview(auth, adapter_source)
    assert (
        auth.post(
            f"/api/outreach-drafts/{adapter_source[2].id}/form-adapter-request",
            json={
                "expected_preparation_hash": seen["preparation_hash"],
                "confirmed": True,
            },
        ).status_code
        == 422
    )
    assert (
        auth.post(
            f"/api/projects/{adapter_source[0].id}/approval-requests", json=seen["proposal"]
        ).status_code
        == 409
    )


@pytest.mark.parametrize("change", ["draft", "sender", "profile", "hash"])
def test_stale_preview_cannot_prepare(auth, adapter_source, db, change):
    seen = preview(auth, adapter_source)
    if change == "draft":
        adapter_source[2].body = "changed"
    elif change == "sender":
        adapter_source[4].contact_name = "changed"
    elif change == "profile":
        adapter_source[3].fingerprint = "c" * 64
    else:
        seen["preparation_hash"] = "0" * 64
    db.commit()
    assert (
        auth.post(
            f"/api/outreach-drafts/{adapter_source[2].id}/form-adapter-request",
            json={"expected_preparation_hash": seen["preparation_hash"]},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("change", ["draft", "sender", "profile", "expiry"])
def test_approved_dependencies_changed_cannot_reserve(
    auth, adapter_source, db, monkeypatch, change
):
    item = prepare(auth, adapter_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    if change == "draft":
        adapter_source[2].body = "changed"
    elif change == "sender":
        adapter_source[4].contact_name = "changed"
    elif change == "profile":
        adapter_source[3].fingerprint = "c" * 64
    else:
        from datetime import timedelta

        frozen = human_approval.now() + timedelta(hours=25)
        monkeypatch.setattr(human_approval, "now", lambda: frozen)
    db.commit()
    assert reserve(auth, item).status_code == 409
    assert db.scalar(select(func.count()).select_from(ApprovedFormDispatch)) == 0


def test_reservation_db_guard_and_cancel(auth, adapter_source, db):
    item = prepare(auth, adapter_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    result = reserve(auth, item).json()
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.execute(
            text("UPDATE approved_form_dispatches SET status='checking' WHERE id=:id"),
            {"id": result["id"]},
        )
    assert error.value.orig.diag.constraint_name == "ck_adapter_reservation_not_started"
    # Downgrade must retain the safety constraint when reservation evidence exists.
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/fd3f8cae4215_adapter_reservation_guard.py"
    )
    spec = importlib.util.spec_from_file_location("adapter_reservation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(IntegrityError, match="downgrade forbidden"), db.begin_nested():
        with Operations.context(MigrationContext.configure(db.connection())):
            migration.downgrade()
    assert (
        auth.post(f"/api/approved-form-dispatches/{result['id']}/cancel").json()["status"]
        == "cancelled"
    )


def test_viewer_and_cross_project(auth, adapter_source, db, users):
    from tests.conftest import PASSWORD

    db.add(ProjectMember(project_id=adapter_source[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert (
        auth.get(f"/api/outreach-drafts/{adapter_source[2].id}/form-adapter-preview").status_code
        == 404
    )
    assert auth.get(f"/api/outreach-drafts/{UUID(int=999)}/form-adapter-preview").status_code == 404


def test_agent_and_mixed_cookie_refused(auth, adapter_source, monkeypatch):
    monkeypatch.setattr(settings, "agent_features_enabled", True)
    token = agent_token(auth, (adapter_source[0], adapter_source[1]))
    headers = {"Authorization": "Bearer " + token["token"]}
    path = f"/api/outreach-drafts/{adapter_source[2].id}/form-adapter-preview"
    assert auth.get(path, headers=headers).status_code == 403
    auth.cookies.clear()
    assert auth.get(path, headers=headers).status_code == 403


@pytest.mark.parametrize("change", ["long_body", "bad_fingerprint"])
def test_invalid_stored_contract_is_public_conflict(auth, adapter_source, db, change):
    if change == "long_body":
        adapter_source[2].body = "x" * 20001
    else:
        adapter_source[3].fingerprint = "not-a-digest"
    db.commit()
    result = auth.get(f"/api/outreach-drafts/{adapter_source[2].id}/form-adapter-preview")
    assert result.status_code == 409
    assert "validation" not in result.text.lower()


def test_duplicate_between_adapter_and_direct(auth, adapter_source):
    from tests.test_form_approval_preparation import prepare as prepare_direct

    item = prepare(auth, adapter_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    assert reserve(auth, item).status_code == 201
    direct = prepare_direct(auth, adapter_source)
    assert approve(auth, direct, challenge(auth, direct)).status_code == 200
    assert reserve(auth, direct).status_code == 409
