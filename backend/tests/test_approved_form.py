from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import ApprovalRequest, ApprovedFormDispatch, FormDelivery
from app.services import approved_form as service
from app.services import approved_form_worker as worker
from app.services import human_approval as approval
from app.services.form_delivery import FormDeliveryError, FormField, FormPreview
from app.services.form_delivery_result import FormSubmissionResult
from app.services.form_profile_delivery import DeliveryProfileContext
from tests.test_approval_foundation import approve, challenge, expected
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source
from tests.test_form_approval_preparation import prepare


@pytest.fixture
def approved(auth, form_source, db):
    form_source[3].action_url = form_source[3].form_url + "/submit"
    form_source[2].body = "本文" * 1500
    db.commit()
    item = prepare(auth, form_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    return item


def reserve(auth, item, key=None):
    return auth.post(
        f"/api/approval-requests/{item['id']}/form-dispatch",
        json={
            **expected(item),
            "idempotency_key": str(key or uuid4()),
        },
    )


@pytest.fixture
def executor(monkeypatch, form_source):
    monkeypatch.setattr(settings, "outbound_enabled", True)
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    _, _, _, profile, _, fields = form_source

    def inspect(*args):
        preview = FormPreview(
            profile.form_url,
            profile.action_url,
            [
                FormField(f.name, f.label, f.field_type, f.required, "", [], f.mapped_key)
                for f in fields
            ],
            profile.id,
            "READY",
            profile.fingerprint,
        )
        return DeliveryProfileContext(profile, fields, preview, {})

    monkeypatch.setattr(worker, "inspect_delivery_profile", inspect)


def test_reservation_idempotency_and_no_send(auth, approved, db, monkeypatch):
    monkeypatch.setattr(settings, "outbound_enabled", False)
    key = uuid4()
    first = reserve(auth, approved, key)
    assert first.status_code == 201, first.text
    assert reserve(auth, approved, key).json()["id"] == first.json()["id"]
    assert reserve(auth, approved | {"payload_version": 2}, key).status_code == 409
    assert reserve(auth, approved).status_code == 409
    assert service.claim(db) is None
    assert db.get(ApprovalRequest, UUID(approved["id"])).status == "APPROVED"
    assert not db.scalar(select(FormDelivery))


@pytest.mark.parametrize(
    "fault", ["hash", "version", "not_approved", "expired", "sender", "action", "prohibited"]
)
def test_invalid_reservation(auth, approved, db, form_source, fault):
    if fault == "hash":
        approved["payload_hash"] = "0" * 64
    elif fault == "version":
        approved["payload_version"] += 1
    elif fault == "not_approved":
        auth.post(
            f"/api/approval-requests/{approved['id']}/revoke",
            json={**expected(approved), "reason": "取消"},
        )
    elif fault == "expired":
        row = db.get(ApprovalRequest, UUID(approved["id"]))
        # Expire via clock, not immutable request mutation.
        from unittest.mock import patch

        with patch.object(approval, "now", return_value=row.expires_at + timedelta(seconds=1)):
            assert reserve(auth, approved).status_code == 409
        return
    elif fault == "sender":
        form_source[4].email = "changed@example.com"
    elif fault == "action":
        form_source[3].action_url += "-changed"
    else:
        form_source[1].do_not_contact = True
    db.commit()
    assert reserve(auth, approved).status_code == 409


def test_atomic_consume_fixed_payload_and_single_post(auth, approved, executor, db, monkeypatch):
    assert reserve(auth, approved).status_code == 201
    claimed = service.claim(db)
    posts = []

    def submit(url, values, **kwargs):
        posts.append(values)
        db.rollback()
        assert db.get(ApprovalRequest, UUID(approved["id"])).status == "CONSUMED"
        assert db.scalar(select(FormDelivery)).status == "unknown"
        assert len(values["message"]) == 3000
        assert kwargs["expected_action_url"].endswith("/submit")
        return None, FormSubmissionResult(200, url + "/thanks", False, "送信完了")

    monkeypatch.setattr(worker, "submit_form", submit)
    worker.run(db, claimed)
    db.expire_all()
    assert db.get(ApprovedFormDispatch, claimed.id).status == "submitted"
    assert service.claim(db) is None
    worker.run(db, db.get(ApprovedFormDispatch, claimed.id))
    assert len(posts) == 1
    assert reserve(auth, approved).status_code == 409


@pytest.mark.parametrize("failure", ["unknown", "crash", "pre_post"])
def test_attempt_failure_is_not_retried(auth, approved, executor, db, monkeypatch, failure):
    reserve(auth, approved)
    claimed = service.claim(db)

    def submit(*args, **kwargs):
        if failure == "crash":
            raise RuntimeError("private internal details")
        raise FormDeliveryError("送信失敗", submission_unknown=failure == "unknown")

    monkeypatch.setattr(worker, "submit_form", submit)
    worker.run(db, claimed)
    db.expire_all()
    assert db.get(ApprovedFormDispatch, claimed.id).status == (
        "failed" if failure == "pre_post" else "unknown"
    )
    assert service.claim(db) is None
    assert reserve(auth, approved).status_code == 409
    assert "private" not in db.get(ApprovedFormDispatch, claimed.id).reason


@pytest.mark.parametrize("change", ["sender", "suppression", "action", "cancel", "revoke"])
def test_changed_after_queue_blocks_post(
    auth, approved, executor, form_source, db, monkeypatch, change
):
    response = reserve(auth, approved)
    row_id = response.json()["id"]
    claimed = service.claim(db)
    if change == "sender":
        form_source[4].phone = "123"
    elif change == "suppression":
        form_source[1].do_not_contact = True
    elif change == "action":
        form_source[3].action_url += "/changed"
    elif change == "cancel":
        assert auth.post(f"/api/approved-form-dispatches/{row_id}/cancel").status_code == 200
    else:
        auth.post(
            f"/api/approval-requests/{approved['id']}/revoke",
            json={**expected(approved), "reason": "取消"},
        )
    db.commit()
    monkeypatch.setattr(worker, "submit_form", lambda *a, **k: pytest.fail("No POST allowed"))
    worker.run(db, claimed)
    assert db.get(ApprovedFormDispatch, UUID(row_id)).status in {"blocked", "cancelled"}


def test_worker_loss_before_post_and_immutable_reservation(auth, approved, executor, db):
    reserve(auth, approved)
    claimed = service.claim(db)
    context = worker.inspect_delivery_profile()
    assert worker.begin(db, claimed.id, claimed.worker_id, context)
    db.rollback()
    assert service.claim(db) is None
    assert db.get(ApprovalRequest, UUID(approved["id"])).status == "CONSUMED"
    with pytest.raises(IntegrityError), db.begin_nested():
        db.get(ApprovedFormDispatch, claimed.id).payload_hash = "0" * 64
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.delete(db.get(ApprovedFormDispatch, claimed.id))
        db.flush()


@pytest.mark.parametrize("path", ["direct", "assist", "batch", "retry"])
def test_legacy_confirmed_is_disabled(auth, form_source, monkeypatch, path):
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)
    if path == "assist":
        result = auth.get(f"/api/outreach-drafts/{form_source[2].id}/form-assist")
    else:
        url = {
            "direct": f"/api/outreach-drafts/{form_source[2].id}/form-delivery",
            "batch": f"/api/form-delivery-batches/{uuid4()}/execute",
            "retry": f"/api/form-delivery-batch-items/{uuid4()}/retry",
        }[path]
        result = auth.post(url, json={"confirmed": True})
    assert result.status_code == 403, result.text


def test_attempt_spacing_counts_unknown(auth, approved, executor, db, monkeypatch):
    reserve(auth, approved)
    claimed = service.claim(db)
    worker.begin(db, claimed.id, claimed.worker_id, worker.inspect_delivery_profile())
    started = db.get(ApprovedFormDispatch, claimed.id).started_at
    monkeypatch.setattr(approval, "now", lambda: started + timedelta(seconds=59))
    assert not service.capacity(db)
    monkeypatch.setattr(approval, "now", lambda: started + timedelta(seconds=60))
    assert service.capacity(db)


def test_disabled_legacy_queue_is_readable_without_send_tasks(auth, form_source, db, monkeypatch):
    project, company, _, profile, _, _ = form_source
    profile.form_status = "REVIEW_REQUIRED"
    db.commit()
    template = auth.post(
        f"/api/projects/{project.id}/outreach-templates",
        json={
            "name": "フォーム",
            "channel": "form",
            "subject": "提案",
            "body": "本文",
        },
    )
    assert template.status_code == 201, template.text
    batch = auth.post(
        f"/api/projects/{project.id}/form-delivery-batches",
        json={
            "template_id": template.json()["id"],
            "company_ids": [str(company.id)],
        },
    )
    assert batch.status_code == 201, batch.text
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)
    response = auth.get(f"/api/projects/{project.id}/form-codex-queue")
    assert response.status_code == 200
    assert response.json() == []


def test_rate_and_preflight_lease(auth, approved, executor, db, monkeypatch):
    reserve(auth, approved)
    monkeypatch.setattr(service, "capacity", lambda db: False)
    assert service.claim(db) is None
    monkeypatch.setattr(service, "capacity", lambda db: True)
    claimed = service.claim(db)
    clock = approval.now()
    monkeypatch.setattr(
        approval, "now", lambda: clock + timedelta(seconds=settings.worker_lease_seconds + 1)
    )
    assert service.claim(db) is None
    assert db.get(ApprovedFormDispatch, claimed.id).status == "blocked"


def test_consume_without_durable_evidence_is_rejected(approved, db):
    with pytest.raises(IntegrityError), db.begin_nested():
        db.get(ApprovalRequest, UUID(approved["id"])).status = "CONSUMED"
        db.flush()


@pytest.mark.parametrize("confirmation", [True, None])
def test_multistage_requires_human_review(auth, approved, form_source, db, confirmation):
    form_source[3].confirmation_page = confirmation
    db.commit()
    item = prepare(auth, form_source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    result = reserve(auth, item)
    assert result.status_code == 409
    assert "確認画面" in result.json()["detail"]


def test_caller_cannot_override_approved_fields(auth, approved):
    result = auth.post(
        f"/api/approval-requests/{approved['id']}/form-dispatch",
        json={
            **expected(approved),
            "idempotency_key": str(uuid4()),
            "confirmed": True,
            "field_values": {"message": "違う本文"},
        },
    )
    assert result.status_code == 422


def test_live_action_change_blocks_without_post(auth, approved, executor, db, monkeypatch):
    from dataclasses import replace

    reserve(auth, approved)
    claimed = service.claim(db)
    context = worker.inspect_delivery_profile()
    changed = replace(
        context, preview=replace(context.preview, action_url="https://approval.example/changed")
    )
    monkeypatch.setattr(worker, "inspect_delivery_profile", lambda *a: changed)
    monkeypatch.setattr(worker, "submit_form", lambda *a, **k: pytest.fail("No POST"))
    worker.run(db, claimed)
    assert db.get(ApprovedFormDispatch, claimed.id).status == "blocked"
    assert db.get(ApprovalRequest, UUID(approved["id"])).status == "APPROVED"
    assert not db.scalar(select(FormDelivery))


@pytest.mark.parametrize("mixed", [False, True])
def test_agent_cannot_reserve_or_cancel(auth, approved, form_source, monkeypatch, mixed):
    from tests.test_approval_foundation import agent_token

    monkeypatch.setattr(settings, "agent_features_enabled", True)
    row = reserve(auth, approved).json()
    token = agent_token(auth, form_source[:2])["token"]
    if not mixed:
        auth.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        auth.post(
            f"/api/approval-requests/{approved['id']}/form-dispatch",
            headers=headers,
            json={**expected(approved), "idempotency_key": str(uuid4())},
        ).status_code
        == 403
    )
    assert (
        auth.post(f"/api/approved-form-dispatches/{row['id']}/cancel", headers=headers).status_code
        == 403
    )


def test_project_and_viewer_boundaries(auth, approved, form_source, users, db):
    from app.models import ProjectMember
    from tests.conftest import PASSWORD

    row = reserve(auth, approved).json()
    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    project_id = form_source[0].id
    assert auth.get(f"/api/projects/{project_id}/approved-form-dispatches").status_code == 404
    db.add(ProjectMember(project_id=project_id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(f"/api/projects/{project_id}/approved-form-dispatches").status_code == 200
    assert reserve(auth, approved).status_code == 404
    assert auth.post(f"/api/approved-form-dispatches/{row['id']}/cancel").status_code == 404
