"""P3: immutable lineage and fresh human proof, no dispatch."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import ApprovalRequest, CF7Observation, OutreachAuditEvent, ProjectMember
from app.services import human_approval as approval
from tests.test_approval_foundation import approve, challenge, expected
from tests.test_approval_foundation import workspace as workspace
from tests.test_cf7_candidate_preparation import prepare
from tests.test_cf7_candidate_preparation import source as source


def revision_preview(auth, old):
    return auth.post(
        f"/api/approval-requests/{old['id']}/cf7-revision-preview",
        json={**expected(old), "selections": [{"name": "consent", "checked": True}]},
    )


def revise(auth, old, preview):
    return auth.post(
        f"/api/approval-requests/{old['id']}/cf7-revisions",
        json={
            **expected(old),
            "selections": [{"name": "consent", "checked": True}],
            "expected_preparation_hash": preview["preparation_hash"],
        },
    )


def test_revision_keeps_lineage_and_requires_fresh_proof(auth, source, db):
    old = prepare(auth, source)
    token = challenge(auth, old)
    assert approve(auth, old, token).status_code == 200
    source[2].body = "Changed draft\n日本語"
    db.commit()
    prepared = revision_preview(auth, old)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["cf7_candidate_snapshot"]["contract"]["payload_version"] == 2
    result = revise(auth, old, prepared.json())
    assert result.status_code == 201, result.text
    new = result.json()
    assert new["proposal_id"] == old["proposal_id"]
    assert new["supersedes_request_id"] == old["id"]
    assert new["payload_version"] == 2 and new["status"] == "PENDING"
    assert new["body"] == source[2].body and new["payload_hash"] != old["payload_hash"]
    assert new["cf7_observation"]["evidence_hash"] == source[5].evidence_hash
    db.expire_all()
    previous = db.get(ApprovalRequest, source_id(old))
    assert previous.status == "REVOKED"
    assert previous.payload_hash == old["payload_hash"] and previous.body == old["body"]
    assert approve(auth, new, token).status_code == 403
    assert approve(auth, new, challenge(auth, new)).status_code == 200
    assert revise(auth, old, prepared.json()).status_code == 409
    events = db.scalars(
        select(OutreachAuditEvent).where(
            OutreachAuditEvent.request_id.in_([previous.id, source_id(new)])
        )
    ).all()
    assert any(e.event == "revision created" and e.payload_version == 2 for e in events)
    assert any(e.event == "revoked" and e.reason == "superseded by CF7 revision" for e in events)
    assert auth.post(
        f"/api/approval-requests/{new['id']}/form-dispatch",
        json={
            **expected(new),
            "idempotency_key": "cf7-revision-no-send",
        },
    ).status_code in {409, 422}


def source_id(item):
    from uuid import UUID

    return UUID(item["id"])


@pytest.mark.parametrize("status", ["PENDING", "APPROVED", "REVOKED", "REJECTED"])
def test_terminal_or_active_candidate_can_be_reprepared_but_never_reuses_approval(
    auth,
    source,
    db,
    status,
):
    old = prepare(auth, source)
    if status == "APPROVED":
        assert approve(auth, old, challenge(auth, old)).status_code == 200
    elif status in {"REVOKED", "REJECTED"}:
        action = "revoke" if status == "REVOKED" else "reject"
        assert (
            auth.post(
                f"/api/approval-requests/{old['id']}/{action}",
                json={
                    **expected(old),
                    "reason": "Human review",
                },
            ).status_code
            == 200
        )
    prepared = revision_preview(auth, old)
    assert prepared.status_code == 200
    new = revise(auth, old, prepared.json())
    assert new.status_code == 201, new.text
    assert new.json()["approved_by_user_id"] is None
    assert new.json()["approved_at"] is None
    assert new.json()["approved_payload_hash"] is None
    db.expire_all()
    assert db.get(ApprovalRequest, source_id(old)).status == (
        "REVOKED" if status in {"PENDING", "APPROVED"} else status
    )


def test_stale_revision_and_forbidden_payload_do_not_revoke_old_approval(auth, source, db):
    old = prepare(auth, source)
    assert approve(auth, old, challenge(auth, old)).status_code == 200
    prepared = revision_preview(auth, old).json()
    source[2].body += " changed"
    db.commit()
    assert revise(auth, old, prepared).status_code == 409
    for overrides in ({"body": "override"}, {"confirmed": True}, {"expected_version": 99}):
        body = {**expected(old), "selections": [{"name": "consent", "checked": True}], **overrides}
        result = auth.post(f"/api/approval-requests/{old['id']}/cf7-revision-preview", json=body)
        assert result.status_code == (409 if "expected_version" in overrides else 422)
    db.expire_all()
    assert db.get(ApprovalRequest, source_id(old)).status == "APPROVED"
    assert (
        len(
            db.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.proposal_id == source_id({"id": old["proposal_id"]})
                )
            ).all()
        )
        == 1
    )


@pytest.mark.parametrize("read_expiry_first", [False, True])
def test_expired_evidence_requires_new_observation(
    auth, source, db, monkeypatch, read_expiry_first
):
    old = prepare(auth, source)
    later = source[5].expires_at + timedelta(seconds=1)
    monkeypatch.setattr(approval, "now", lambda: later)
    if read_expiry_first:
        assert auth.get(f"/api/approval-requests/{old['id']}").json()["status"] == "EXPIRED"
    assert revision_preview(auth, old).status_code == 409
    original = source[5]
    db.add(
        CF7Observation(
            project_id=original.project_id,
            company_id=original.company_id,
            form_profile_id=original.form_profile_id,
            source_kind=original.source_kind,
            observer_version=original.observer_version,
            observed_at=later,
            expires_at=later + timedelta(hours=1),
            evidence_snapshot=original.evidence_snapshot,
            evidence_hash=original.evidence_hash,
            created_by_user_id=original.created_by_user_id,
        )
    )
    db.commit()
    result = revise(auth, old, revision_preview(auth, old).json())
    assert result.status_code == 201
    assert result.json()["payload_version"] == 2
    db.expire_all()
    assert db.get(ApprovalRequest, source_id(old)).status == "EXPIRED"


def test_revision_boundaries_reject_agent_viewer_and_other_project(auth, source, db, users):
    from tests.conftest import PASSWORD

    old = prepare(auth, source)
    path = f"/api/approval-requests/{old['id']}"
    body = {**expected(old), "selections": [{"name": "consent", "checked": True}]}
    calls = [
        ("GET", path + "/cf7-revision-preview", None),
        ("POST", path + "/cf7-revision-preview", body),
        ("POST", path + "/cf7-revisions", {**body, "expected_preparation_hash": "a" * 64}),
    ]
    for method, url, payload in calls:
        assert (
            auth.request(
                method, url, json=payload, headers={"Authorization": "Bearer fake"}
            ).status_code
            == 403
        )
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    for role in (None, "viewer"):
        if role:
            db.add(ProjectMember(project_id=source[0].id, user_id=users[1].id, role=role))
            db.commit()
        for method, url, payload in calls:
            assert auth.request(method, url, json=payload).status_code == 404


def test_revision_does_not_bypass_contact_prohibition(auth, source, db):
    old = prepare(auth, source)
    prepared = revision_preview(auth, old).json()
    source[1].do_not_contact = True
    db.commit()
    assert revise(auth, old, prepared).status_code == 409
    assert revision_preview(auth, old).status_code == 409
