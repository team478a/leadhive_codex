"""Human operations preserve send evidence and never dispatch or retry."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    FormDelivery,
    OutreachAuditEvent,
    ProjectMember,
)
from app.services import (
    approved_form as service,
)
from app.services import (
    approved_form_worker as worker,
)
from app.services import (
    human_approval as approval,
)
from tests.conftest import PASSWORD
from tests.test_approval_foundation import expected
from tests.test_approval_foundation import workspace as workspace
from tests.test_approved_form import approved as approved
from tests.test_approved_form import executor as executor
from tests.test_approved_form import reserve
from tests.test_form_approval_preparation import form_source as form_source


def overview(auth, source, category="attention"):
    return auth.get(f"/api/projects/{source[0].id}/form-operations?category={category}")


def stopped(auth, approved):
    row = reserve(auth, approved).json()
    assert auth.post(f"/api/approved-form-dispatches/{row['id']}/cancel").status_code == 200
    return row


def reprepare(auth, row, approved, preview):
    return auth.post(
        f"/api/approved-form-dispatches/{row['id']}/reprepare",
        json={
            **expected(approved),
            "expected_preparation_hash": preview["preparation_hash"],
        },
    )


def test_read_expiry_is_nonmutating_and_worker_reconciles_when_off(
    auth, approved, form_source, db, monkeypatch
):
    row = reserve(auth, approved).json()
    future = datetime.fromisoformat(approved["expires_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(approval, "now", lambda: future)
    view = overview(auth, form_source).json()
    assert view["counts"] == {"expired": 1}
    assert view["items"][0]["can_reprepare"]
    assert db.get(ApprovedFormDispatch, UUID(row["id"])).status == "queued"
    assert db.get(ApprovalRequest, UUID(approved["id"])).status == "APPROVED"
    monkeypatch.setattr(settings, "outbound_enabled", False)
    assert service.claim(db) is None
    assert db.get(ApprovedFormDispatch, UUID(row["id"])).status == "blocked"
    assert db.get(ApprovalRequest, UUID(approved["id"])).status == "EXPIRED"
    assert not db.scalar(select(FormDelivery))
    assert (
        auth.post(f"/api/projects/{form_source[0].id}/form-operations/reconcile").json()[
            "processed"
        ]
        == 0
    )


def test_stopped_reprepare_is_pending_idempotent_and_does_not_send(auth, approved, form_source, db):
    row = stopped(auth, approved)
    prefix = f"/api/approved-form-dispatches/{row['id']}"
    preview = auth.get(prefix + "/reprepare-preview")
    assert preview.status_code == 200, preview.text
    response = reprepare(auth, row, approved, preview.json())
    assert response.status_code == 201, response.text
    new_item = response.json()
    assert new_item["status"] == "PENDING" and new_item["id"] != approved["id"]
    assert reprepare(auth, row, approved, preview.json()).json()["id"] == new_item["id"]
    assert db.get(ApprovalRequest, UUID(approved["id"])).status == "REVOKED"
    assert not db.scalar(select(FormDelivery))
    assert (
        len(
            db.scalars(
                select(ApprovedFormDispatch).where(
                    ApprovedFormDispatch.project_id == form_source[0].id
                )
            ).all()
        )
        == 1
    )
    assert (
        db.scalar(
            select(OutreachAuditEvent).where(
                OutreachAuditEvent.event == "form repreparation linked"
            )
        ).reason
        == new_item["id"]
    )


def test_checking_expiry_fences_active_preflight(
    auth, approved, form_source, executor, db, monkeypatch
):
    reserve(auth, approved)
    claimed = service.claim(db)
    monkeypatch.setattr(
        approval,
        "now",
        lambda: datetime.fromisoformat(approved["expires_at"]) + timedelta(seconds=1),
    )
    assert overview(auth, form_source).json()["counts"] == {"expired": 1}
    assert (
        auth.post(f"/api/projects/{form_source[0].id}/form-operations/reconcile").json()[
            "processed"
        ]
        == 1
    )
    assert (
        worker.begin(db, claimed.id, claimed.worker_id, worker.inspect_delivery_profile()) is None
    )
    assert not db.scalar(select(FormDelivery))


@pytest.mark.parametrize("change", ["source", "hash", "version", "suppression", "active_proposal"])
def test_reprepare_conflicts_fail_closed(auth, approved, form_source, db, change):
    row = stopped(auth, approved)
    preview = auth.get(f"/api/approved-form-dispatches/{row['id']}/reprepare-preview").json()
    if change == "source":
        form_source[2].body += " changed"
    elif change == "hash":
        approved["payload_hash"] = "0" * 64
    elif change == "version":
        approved["payload_version"] += 1
    elif change == "suppression":
        form_source[1].do_not_contact = True
    else:
        from tests.test_form_approval_preparation import prepare

        prepare(auth, form_source)
    db.commit()
    assert reprepare(auth, row, approved, preview).status_code == 409
    assert not db.scalar(select(FormDelivery))


def test_unknown_review_does_not_change_result_unlock_or_expire(
    auth, approved, form_source, executor, db, monkeypatch
):
    row = reserve(auth, approved).json()
    claimed = service.claim(db)
    worker.begin(db, claimed.id, claimed.worker_id, worker.inspect_delivery_profile())
    prefix = f"/api/approved-form-dispatches/{row['id']}"
    assert auth.get(prefix + "/reprepare-preview").status_code == 409
    assert auth.post(
        prefix + "/review", json={**expected(approved), "choice": "received"}
    ).json() == {"recorded": True, "status": "unknown", "retry_allowed": False}
    monkeypatch.setattr(
        approval,
        "now",
        lambda: datetime.fromisoformat(approved["expires_at"]) + timedelta(seconds=1),
    )
    result = overview(auth, form_source).json()
    assert result["counts"] == {"unknown": 1}
    assert result["items"][0]["review"]["choice"] == "received"
    assert not result["items"][0]["can_reprepare"]
    assert service.claim(db) is None
    assert db.get(ApprovalRequest, UUID(approved["id"])).status == "CONSUMED"
    assert db.get(ApprovedFormDispatch, claimed.id).status == "unknown"
    assert db.scalar(select(FormDelivery)).status == "unknown"
    assert reserve(auth, approved).status_code == 409


def test_running_and_unknown_cannot_reprepare_and_review_is_strict(auth, approved, executor, db):
    row = reserve(auth, approved).json()
    prefix = f"/api/approved-form-dispatches/{row['id']}"
    assert auth.get(prefix + "/reprepare-preview").status_code == 409
    assert (
        auth.post(prefix + "/review", json={**expected(approved), "choice": "received"}).status_code
        == 409
    )
    claimed = service.claim(db)
    assert auth.get(prefix + "/reprepare-preview").status_code == 409
    worker.begin(db, claimed.id, claimed.worker_id, worker.inspect_delivery_profile())
    assert (
        auth.post(
            prefix + "/review", json={**expected(approved), "choice": "received", "confirmed": True}
        ).status_code
        == 422
    )
    assert (
        auth.post(prefix + "/review", json={**expected(approved), "choice": "retry"}).status_code
        == 422
    )
    assert (
        auth.post(
            prefix + "/review",
            json={**expected(approved), "choice": "received", "expected_version": 2},
        ).status_code
        == 409
    )


def test_reconcile_is_bounded(auth, approved, form_source, db, monkeypatch):
    from tests.test_form_site_rate import seed_queue

    reserve(auth, approved)
    seed_queue(db, approved, form_source, 121)
    monkeypatch.setattr(
        approval,
        "now",
        lambda: datetime.fromisoformat(approved["expires_at"]) + timedelta(seconds=1),
    )
    prefix = f"/api/projects/{form_source[0].id}/form-operations/reconcile"
    assert auth.post(prefix).json()["processed"] == 100
    assert auth.post(prefix).json()["processed"] == 22
    assert auth.post(prefix).json()["processed"] == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(ApprovedFormDispatch)
            .where(ApprovedFormDispatch.status == "blocked")
        )
        == 122
    )


def test_project_viewer_and_filter_pagination(auth, approved, form_source, users, db):
    stopped(auth, approved)
    assert overview(auth, form_source).json()["total"] == 0
    assert overview(auth, form_source, "all").json()["total"] == 1
    assert (
        auth.get(f"/api/projects/{form_source[0].id}/form-operations?offset=1&category=all").json()[
            "items"
        ]
        == []
    )
    assert overview(auth, form_source, "invalid").status_code == 422
    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert overview(auth, form_source).status_code == 404
    db.add(ProjectMember(project_id=form_source[0].id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert overview(auth, form_source, "all").status_code == 200
    assert (
        auth.post(f"/api/projects/{form_source[0].id}/form-operations/reconcile").status_code == 404
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_agent_cannot_operate_or_review(auth, approved, form_source, monkeypatch, mixed):
    from tests.test_approval_foundation import agent_token

    monkeypatch.setattr(settings, "agent_features_enabled", True)
    row = stopped(auth, approved)
    token = agent_token(auth, form_source[:2])["token"]
    if not mixed:
        auth.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        auth.get(f"/api/projects/{form_source[0].id}/form-operations", headers=headers).status_code
        == 403
    )
    assert (
        auth.post(
            f"/api/projects/{form_source[0].id}/form-operations/reconcile", headers=headers
        ).status_code
        == 403
    )
    assert (
        auth.post(
            f"/api/approved-form-dispatches/{row['id']}/review",
            headers=headers,
            json={**expected(approved), "choice": "received"},
        ).status_code
        == 403
    )
