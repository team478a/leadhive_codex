"""Real approval persistence with fabricated confirmation evidence; no dispatch."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.model_approval import ApprovalRequest, HumanApprovalProof
from app.models import ApprovedFormDispatch, EmailDelivery, FormDelivery
from app.services.form_execution_plan import ExecutionPlan, InputValue, plan_hash
from tests.test_approval_foundation import approve, challenge, expected
from tests.test_approval_foundation import workspace as workspace
from tests.test_multipart_confirmation_fixture import confirmation, plan, review


@pytest.fixture(autouse=True)
def outbound_off(monkeypatch, legacy_delivery_test_mode):
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)


def proposal(workspace, version=1):
    sender = {"name": "Human", "email": "fixture@example.com", "company": "", "phone": ""}
    item = plan().model_copy(
        update={
            "project_id": workspace[0].id,
            "company_id": workspace[1].id,
            "payload_version": version,
            "sender": tuple(InputValue(name=k, value=v) for k, v in sender.items()),
        }
    )
    return {
        "company_id": str(workspace[1].id),
        "channel": "form",
        "delivery_method": "form_plan_fixture",
        "form_url": item.form_url,
        "form_action_url": item.steps[-1].url,
        "subject": item.subject,
        "body": item.body,
        "sender": sender,
        "field_values": {v.name: v.value for v in item.field_values},
        "execution_plan": item.model_dump(mode="json"),
    }


def create(auth, workspace):
    response = auth.post(
        f"/api/projects/{workspace[0].id}/approval-requests", json=proposal(workspace)
    )
    assert response.status_code == 201, response.text
    return response.json()


def no_dispatch(db):
    for model in (ApprovedFormDispatch, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert not settings.outbound_enabled and not settings.legacy_form_delivery_enabled


def inspect(item, **changes):
    snapshot = ExecutionPlan.model_validate_json(json.dumps(item["execution_plan"]))
    now = datetime.now(timezone.utc)
    parameters = dict(
        snapshot=snapshot,
        current=snapshot,
        html=confirmation(),
        expected_hash=item["execution_plan_hash"],
        expected_version=item["payload_version"],
        token_payload_hash=plan_hash(snapshot),
        expires_at=now + timedelta(minutes=5),
        now=now,
        observation_id=UUID(int=3),
    )
    parameters.update(changes)
    return review(**parameters)


def test_confirmation_evidence_cannot_replace_step_up(auth, workspace, db):
    item = create(auth, workspace)
    assert inspect(item)["status"] == "REVIEW_REQUIRED"
    assert approve(auth, item, "x" * 43).status_code == 403
    assert db.get(ApprovalRequest, item["id"]).status == "PENDING"
    assert db.scalar(select(func.count()).select_from(HumanApprovalProof)) == 0
    no_dispatch(db)


def test_human_proof_binds_multipart_plan_but_never_enables_dispatch(auth, workspace, db):
    item = create(auth, workspace)
    result = approve(auth, item, challenge(auth, item))
    assert result.status_code == 200, result.text
    proof = db.scalar(select(HumanApprovalProof))
    assert str(proof.request_id) == item["id"]
    assert proof.payload_hash == item["payload_hash"]
    assert proof.payload_version == item["payload_version"]
    assert inspect(item)["status"] == "REVIEW_REQUIRED"
    response = auth.post(
        f"/api/approval-requests/{item['id']}/form-dispatch",
        json=expected(item) | {"idempotency_key": str(uuid4())},
    )
    assert response.status_code == 409
    assert db.get(ApprovalRequest, item["id"]).status == "APPROVED"
    no_dispatch(db)


def test_revision_requires_new_human_proof(auth, workspace, db):
    old = create(auth, workspace)
    old_token = challenge(auth, old)
    assert approve(auth, old, old_token).status_code == 200
    revised = proposal(workspace, version=2)
    revised["execution_plan"]["route_fingerprint"] = "c" * 64
    response = auth.post(
        f"/api/approval-requests/{old['id']}/revisions", json=expected(old) | revised
    )
    assert response.status_code == 201, response.text
    new = response.json()
    assert new["payload_hash"] != old["payload_hash"]
    assert new["execution_plan_hash"] != old["execution_plan_hash"]
    assert new["status"] == "PENDING" and new["payload_version"] == 2
    assert db.get(ApprovalRequest, old["id"]).status == "REVOKED"
    assert approve(auth, new, old_token).status_code == 403
    assert approve(auth, new, challenge(auth, new)).status_code == 200
    assert inspect(new)["status"] == "REVIEW_REQUIRED"
    no_dispatch(db)


def test_unknown_confirmation_preserves_approval_without_retry_authority(auth, workspace, db):
    item = create(auth, workspace)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    # Fabricated missing response is evidence only, never a dispatch/consumption event.
    snapshot = ExecutionPlan.model_validate_json(json.dumps(item["execution_plan"]))
    result = review(
        snapshot=snapshot,
        current=snapshot,
        html=None,
        expected_hash=item["execution_plan_hash"],
        expected_version=item["payload_version"],
        token_payload_hash=plan_hash(snapshot),
    )
    assert result["status"] == "UNKNOWN" and not result["automatic_retry_allowed"]
    assert db.get(ApprovalRequest, item["id"]).status == "APPROVED"
    no_dispatch(db)


def test_changed_confirmation_does_not_borrow_existing_human_proof(auth, workspace, db):
    item = create(auth, workspace)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    result = inspect(item, html=confirmation().replace("fixture@example.com", "other@example.com"))
    assert result["status"] == "BLOCKED"
    assert not result["execution_allowed"]
    proof = db.scalar(select(HumanApprovalProof))
    assert proof.payload_hash == item["payload_hash"]
    # Evidence inspection is read-only: it cannot mutate or consume the approval.
    assert db.get(ApprovalRequest, item["id"]).status == "APPROVED"
    no_dispatch(db)
