from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.model_approval import ApprovalRequest, HumanApprovalProof, OutreachAuditEvent
from app.models import ApprovedFormDispatch, EmailDelivery, FormDelivery
from app.services import human_approval as service
from tests.test_approval_foundation import (
    agent_token,
    approve,
    challenge,
    expected,
)
from tests.test_approval_foundation import (
    workspace as workspace,
)
from tests.test_form_execution_plan import plan


def data(workspace, version=1, **changes):
    project, company = workspace
    from app.services.form_execution_plan import InputValue

    sender = {"name": "Human", "email": "sender@example.com", "company": "", "phone": ""}
    item = plan(
        project_id=project.id,
        company_id=company.id,
        payload_version=version,
        sender=tuple(InputValue(name=k, value=v) for k, v in sender.items()),
    )
    return (
        dict(
            company_id=str(company.id),
            channel="form",
            delivery_method="form_plan_fixture",
            form_url=item.form_url,
            form_action_url=item.steps[-1].url,
            sender=sender,
            subject=item.subject,
            body=item.body,
            field_values={v.name: v.value for v in item.field_values},
            execution_plan=item.model_dump(mode="json"),
        )
        | changes
    )


def create(auth, workspace):
    response = auth.post(f"/api/projects/{workspace[0].id}/approval-requests", json=data(workspace))
    assert response.status_code == 201, response.text
    return response.json()


def test_plan_bound_to_human_proof_and_cannot_dispatch(auth, workspace, db):
    item = create(auth, workspace)
    assert item["execution_plan"] == data(workspace)["execution_plan"]
    assert item["payload_snapshot"]["execution_plan_hash"] == item["execution_plan_hash"]
    assert approve(auth, item, "x" * 43).status_code == 403
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    proof = db.scalar(select(HumanApprovalProof).where(HumanApprovalProof.request_id == item["id"]))
    assert proof.payload_hash == item["payload_hash"] and proof.payload_version == 1
    result = auth.post(
        f"/api/approval-requests/{item['id']}/form-dispatch",
        json=expected(item) | {"idempotency_key": str(uuid4())},
    )
    assert result.status_code == 409, result.text
    for model in (ApprovedFormDispatch, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "change",
    [
        {"delivery_method": "form_direct"},
        {"delivery_method": "form_codex"},
        {"body": "different"},
        {"subject": "different"},
        {"field_values": {"message": "different"}},
        {"form_url": "https://other.example/contact"},
        {"form_action_url": "https://fixture.example/confirm"},
        {"sender": {"name": "other", "email": "sender@example.com"}},
        {"execution_plan": None},
    ],
)
def test_legacy_reuse_and_inconsistent_proposal_rejected(auth, workspace, change):
    response = auth.post(
        f"/api/projects/{workspace[0].id}/approval-requests", json=data(workspace, **change)
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "key,value,status",
    [
        ("project_id", str(UUID(int=999)), 409),
        ("company_id", str(UUID(int=999)), 422),
        ("payload_version", 2, 409),
        ("adapter_id", "real_cf7", 422),
    ],
)
def test_boundary_and_unknown_adapter(auth, workspace, key, value, status):
    body = data(workspace)
    body["execution_plan"][key] = value
    response = auth.post(f"/api/projects/{workspace[0].id}/approval-requests", json=body)
    assert response.status_code == status, response.text


def test_revision_invalidates_old_plan_and_challenge(auth, workspace, db):
    old = create(auth, workspace)
    token = challenge(auth, old)
    assert approve(auth, old, token).status_code == 200
    revised = data(workspace, version=2) | expected(old)
    revised["execution_plan"]["route_fingerprint"] = "c" * 64
    result = auth.post(f"/api/approval-requests/{old['id']}/revisions", json=revised)
    assert result.status_code == 201, result.text
    new = result.json()
    assert new["status"] == "PENDING" and new["payload_version"] == 2
    assert new["payload_hash"] != old["payload_hash"]
    assert new["execution_plan_hash"] != old["execution_plan_hash"]
    assert auth.get(f"/api/approval-requests/{old['id']}").json()["status"] == "REVOKED"
    assert approve(auth, new, token).status_code == 403
    assert approve(auth, new, challenge(auth, new)).status_code == 200
    events = db.scalars(
        select(OutreachAuditEvent).where(OutreachAuditEvent.request_id.in_([old["id"], new["id"]]))
    ).all()
    assert {e.event for e in events} >= {
        "proposal created",
        "approval granted",
        "revoked",
        "revision created",
    }


def test_fixture_payload_db_immutable_and_never_consumed(auth, workspace, db):
    item = create(auth, workspace)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE approval_requests SET payload_snapshot='{}'::jsonb WHERE id=:id"),
            {"id": item["id"]},
        )
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            text("UPDATE approval_requests SET status='CONSUMED' WHERE id=:id"), {"id": item["id"]}
        )
    row = db.get(ApprovalRequest, item["id"])
    copied = {c.name: getattr(row, c.name) for c in ApprovalRequest.__table__.columns}
    copied.update(id=uuid4(), proposal_id=uuid4(), status="CONSUMED")
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.execute(ApprovalRequest.__table__.insert().values(**copied))
    assert error.value.orig.diag.constraint_name == "ck_fixture_plan_not_consumed"
    assert db.get(ApprovalRequest, item["id"]).status == "PENDING"


def test_agent_can_propose_but_never_approve(auth, workspace, monkeypatch):
    monkeypatch.setattr(settings, "agent_features_enabled", True)
    issued = agent_token(auth, workspace)
    auth.cookies.clear()
    headers = {"Authorization": "Bearer " + issued["token"]}
    result = auth.post(
        f"/api/agent/projects/{workspace[0].id}/approval-requests",
        headers=headers,
        json=data(workspace),
    )
    assert result.status_code == 201, result.text
    item = result.json()
    assert item["status"] == "PENDING" and item["created_by_principal_type"] == "AGENT"
    for action in ("approve", "reject", "revoke", "challenge"):
        assert (
            auth.post(
                f"/api/approval-requests/{item['id']}/{action}",
                headers=headers,
                json=expected(item) | {"confirmed": True},
            ).status_code
            == 403
        )


def test_legacy_shape_preserved_and_plan_corruption_revoked(auth, workspace, db):
    from tests.test_approval_foundation import create as legacy_create

    legacy = legacy_create(auth, workspace)
    assert "execution_plan" not in legacy["payload_snapshot"]
    item = create(auth, workspace)
    row = db.get(ApprovalRequest, item["id"])
    # Pure invalidation check using a detached clone, not a bypass of DB immutability.
    db.expunge(row)
    row.payload_snapshot = dict(row.payload_snapshot) | {"execution_plan_hash": "0" * 64}
    row.payload_hash = service.payload_hash(row.payload_snapshot)
    service.invalidate_if_needed(db, row)
    assert row.status == "REVOKED" and "binding" in row.invalidation_reason
