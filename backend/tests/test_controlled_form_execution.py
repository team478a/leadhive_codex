from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import ApprovalRequest, ApprovedFormDispatch, FormDelivery, OutreachAuditEvent
from app.services import approved_form, approved_form_worker, controlled_form_execution
from tests.controlled_adapter_transport import LabTransport
from tests.fixture_plan_http import FixtureServer
from tests.test_approval_foundation import approve, challenge
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_adapter_preparation import adapter_source as adapter_source
from tests.test_form_adapter_preparation import prepare, reserve
from tests.test_form_approval_preparation import form_source as form_source


@pytest.fixture
def queued(auth, adapter_source, monkeypatch):
    monkeypatch.setenv("FORM_ADAPTER_LAB", "1")
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    monkeypatch.setattr(settings, "form_adapter_lab_execution_enabled", True)
    item = prepare(auth, adapter_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    result = reserve(auth, item)
    assert result.status_code == 201
    return item, UUID(result.json()["id"])


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "ambiguous",
        "disconnect",
        "timeout",
        "redirect",
        "wrong_form",
        "wrong_attempt",
        "confirmation",
        "mail_sent",
        "duplicate_json",
        "malformed",
        "oversized",
        "truncated",
        "wrong_http",
        "html",
    ],
)
def test_http_results_no_retry(auth, queued, db, mode):
    item, row_id = queued
    assert approved_form.claim(db) is None  # Normal worker never selects lab work.
    claimed = approved_form.claim(db, controlled_lab=True)
    assert claimed.id == row_id
    with FixtureServer(mode) as lab:

        def before_post(attempt):
            assert db.get(ApprovalRequest, item["id"]).status == "CONSUMED"
            assert db.get(FormDelivery, attempt).status == "unknown"
            assert db.get(ApprovedFormDispatch, row_id).status == "unknown"

        controlled_form_execution.run(db, claimed, LabTransport(lab.port, before_post))
        db.expire_all()
        row = db.get(ApprovedFormDispatch, row_id)
        assert row.status == ("submitted" if mode == "success" else "unknown")
        delivery = db.get(FormDelivery, row.delivery_id)
        assert delivery.delivery_method == "adapter"
        result_read = auth.get(f"/api/outreach-drafts/{item['source_draft_id']}/form-delivery")
        assert result_read.status_code == 200
        assert result_read.json()["delivery_method"] == "adapter"
        assert delivery.execution_authorization["adapter_plan_hash"] == item["adapter_plan_hash"]
        assert approved_form.claim(db, controlled_lab=True) is None
        controlled_form_execution.run(db, row, LabTransport(lab.port))
        assert len(lab.posts) == 1
        assert reserve(auth, item).status_code == 409
        events = db.scalars(
            select(OutreachAuditEvent.event).where(OutreachAuditEvent.request_id == item["id"])
        ).all()
        assert "form dispatch started" in events
        assert "form dispatch " + row.status in events


@pytest.mark.parametrize(
    "change",
    ["flag", "suppression", "captcha", "permission", "sender", "draft", "observed_fingerprint"],
)
def test_begin_rechecks_sources_and_flags(queued, adapter_source, db, monkeypatch, change):
    claimed = approved_form.claim(db, controlled_lab=True)
    if change == "flag":
        monkeypatch.setattr(settings, "form_adapter_lab_execution_enabled", False)
    elif change == "suppression":
        adapter_source[1].do_not_contact = True
    elif change == "captcha":
        adapter_source[3].captcha_type = "CAPTCHA_RECAPTCHA"
    elif change == "permission":
        adapter_source[3].sales_contact_status = "PROHIBITED"
    elif change == "sender":
        adapter_source[4].email = "changed@example.com"
    elif change == "draft":
        adapter_source[2].body = "changed"
    db.commit()
    with FixtureServer(
        fingerprint="b" * 64 if change == "observed_fingerprint" else "a" * 64
    ) as lab:
        controlled_form_execution.run(db, claimed, LabTransport(lab.port))
        assert not lab.posts
    assert db.get(ApprovedFormDispatch, queued[1]).status == "blocked"
    assert db.get(ApprovedFormDispatch, queued[1]).delivery_id is None


@pytest.mark.parametrize("fault", ["audit", "commit"])
def test_commit_failure_rolls_back_all_evidence_before_post(queued, db, monkeypatch, fault):
    claimed = approved_form.claim(db, controlled_lab=True)
    original = approved_form_worker.approval.audit

    def failing_audit(db, item, event, *args):
        if fault == "audit" and event == "form dispatch started":
            raise RuntimeError("synthetic transaction failure")
        return original(db, item, event, *args)

    monkeypatch.setattr(approved_form_worker.approval, "audit", failing_audit)
    original_commit = db.commit

    def commit():
        if fault == "commit" and db.get(ApprovedFormDispatch, queued[1]).status == "unknown":
            raise RuntimeError("synthetic begin commit failure")
        original_commit()

    monkeypatch.setattr(db, "commit", commit)
    with FixtureServer() as lab:
        controlled_form_execution.run(db, claimed, LabTransport(lab.port))
        assert not lab.posts
    assert db.get(ApprovalRequest, queued[0]["id"]).status == "APPROVED"
    assert not db.scalar(select(FormDelivery))


def test_attempt_evidence_and_unknown_are_immutable(queued, db):
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    claimed = approved_form.claim(db, controlled_lab=True)
    with FixtureServer("ambiguous") as lab:
        controlled_form_execution.run(db, claimed, LabTransport(lab.port))
    row = db.get(ApprovedFormDispatch, queued[1])
    for sql in (
        "UPDATE form_deliveries SET execution_authorization='{}'::jsonb WHERE id=:id",
        "UPDATE form_deliveries SET status='pending' WHERE id=:id",
        "DELETE FROM form_deliveries WHERE id=:id",
    ):
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(text(sql), {"id": row.delivery_id})
    migration = import_module("migrations.versions.fe409dbf5326_controlled_adapter_evidence")
    with pytest.raises(IntegrityError, match="downgrade forbidden"), db.begin_nested():
        with Operations.context(MigrationContext.configure(db.connection())):
            migration.downgrade()


def test_lab_flag_default_off():
    from app.config import Settings

    assert Settings.model_fields["form_adapter_lab_execution_enabled"].default is False


def test_cancel_during_preflight_prevents_post(auth, queued, db):
    claimed = approved_form.claim(db, controlled_lab=True)
    with FixtureServer() as lab:
        transport = LabTransport(lab.port)
        original = transport.observe

        def cancel(plan):
            preview = original(plan)
            assert auth.post(f"/api/approved-form-dispatches/{queued[1]}/cancel").status_code == 200
            return preview

        transport.observe = cancel
        controlled_form_execution.run(db, claimed, transport)
        assert not lab.posts
    assert db.get(ApprovedFormDispatch, queued[1]).status == "cancelled"


def test_result_commit_failure_keeps_unknown(queued, db, monkeypatch):
    claimed = approved_form.claim(db, controlled_lab=True)
    original = db.commit

    def commit():
        row = db.get(ApprovedFormDispatch, queued[1])
        if row.status == "submitted":
            raise RuntimeError("synthetic result commit failure")
        original()

    monkeypatch.setattr(db, "commit", commit)
    with FixtureServer() as lab:
        with pytest.raises(RuntimeError, match="result commit failure"):
            controlled_form_execution.run(db, claimed, LabTransport(lab.port))
        db.rollback()
        row = db.get(ApprovedFormDispatch, queued[1])
        assert row.status == "unknown"
        assert db.get(ApprovalRequest, queued[0]["id"]).status == "CONSUMED"
        controlled_form_execution.run(db, row, LabTransport(lab.port))
        assert len(lab.posts) == 1


@pytest.mark.parametrize(
    "key", ["approval_id", "payload_hash", "payload_version", "adapter_plan_hash"]
)
def test_db_consumption_rejects_wrong_evidence(queued, db, monkeypatch, key):
    claimed = approved_form.claim(db, controlled_lab=True)
    original = approved_form_worker.reserve_form_submission

    def tampered(*args, **kwargs):
        kwargs["execution_authorization"][key] = "invalid"
        return original(*args, **kwargs)

    monkeypatch.setattr(approved_form_worker, "reserve_form_submission", tampered)
    with FixtureServer() as lab:
        controlled_form_execution.run(db, claimed, LabTransport(lab.port))
        assert not lab.posts
    assert db.get(ApprovalRequest, queued[0]["id"]).status == "APPROVED"
    assert not db.scalar(select(FormDelivery))


@pytest.mark.parametrize("change", ["sender", "suppression", "owner", "paused", "expiry", "flag"])
def test_change_after_observation_blocks_atomic_begin(
    queued, adapter_source, db, monkeypatch, users, change
):
    from datetime import timedelta

    from app.models import FormDispatchLimits
    from app.services import human_approval

    claimed = approved_form.claim(db, controlled_lab=True)
    with FixtureServer() as lab:
        transport = LabTransport(lab.port)
        original = transport.observe

        def observe(plan):
            result = original(plan)
            if change == "sender":
                adapter_source[4].phone = "changed"
            elif change == "suppression":
                adapter_source[1].do_not_contact = True
            elif change == "owner":
                adapter_source[0].user_id = users[1].id
            elif change == "paused":
                db.get(FormDispatchLimits, 1).paused = True
            elif change == "expiry":
                frozen = human_approval.now() + timedelta(hours=25)
                monkeypatch.setattr(human_approval, "now", lambda: frozen)
            else:
                monkeypatch.setattr(settings, "form_adapter_lab_execution_enabled", False)
            db.commit()
            return result

        transport.observe = observe
        controlled_form_execution.run(db, claimed, transport)
        assert not lab.posts
    assert db.get(ApprovedFormDispatch, queued[1]).status == "blocked"
    assert not db.scalar(select(FormDelivery))
