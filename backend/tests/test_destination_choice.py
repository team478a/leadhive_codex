"""Synthetic-only preparation choice: no approval or delivery."""

import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalRequest,
    DestinationChoiceEvent,
    DestinationReviewEvent,
    EmailDelivery,
    FormDelivery,
    Project,
    ProjectMember,
)
from app.services.destination_choice import public_choice
from tests.test_destination_review import reviewed_fixture


def ready(auth, db):
    company, profile, path, review_path, body = reviewed_fixture(auth, db)
    assert auth.post(review_path, json=body).status_code == 201
    result = auth.get(path).json()
    assert result["status"] == "READY"
    item = result["destinations"][0]
    choice_path = f"/api/companies/{company.id}/destinations/{item['id']}/choice"
    choice_body = dict(
        expected_hash=item["expected_hash"],
        expected_purpose_version=item["review"]["version"],
        expected_choice_version=0,
    )
    return company, profile, path, review_path, body, choice_path, choice_body


def test_choice_persistence_versions_revoke_and_no_delivery(auth, db):
    company, _, path, _, _, endpoint, body = ready(auth, db)
    assert auth.get(path).json()["human_choice"]["state"] == "UNSELECTED"
    result = auth.post(endpoint, json=body)
    assert result.status_code == 201, result.text
    assert result.json()["state"] == "CURRENT"
    assert result.json()["active_destination"]["payload_hash"] == body["expected_hash"]
    assert not result.json()["execution_allowed"]
    assert auth.get(path).json()["human_choice"]["version"] == 1
    assert auth.post(endpoint, json=body).status_code == 409
    revoke = f"/api/companies/{company.id}/destination-choice/revoke"
    assert auth.post(revoke, json={"expected_choice_version": 2}).status_code == 409
    result = auth.post(revoke, json={"expected_choice_version": 1})
    assert result.status_code == 201
    assert result.json()["state"] == "REVOKED" and result.json()["active_destination"] is None
    assert auth.post(revoke, json={"expected_choice_version": 2}).status_code == 409
    assert auth.post(endpoint, json={**body, "expected_choice_version": 2}).status_code == 201
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("change", ["purpose", "fingerprint", "ban", "captcha"])
def test_old_choice_is_never_active_after_change(auth, db, change):
    company, profile, path, review_path, purpose_body, endpoint, body = ready(auth, db)
    assert auth.post(endpoint, json=body).status_code == 201
    if change == "purpose":
        assert (
            auth.post(review_path, json={**purpose_body, "expected_review_version": 1}).status_code
            == 201
        )
    elif change == "fingerprint":
        profile.fingerprint = "e" * 64
    elif change == "ban":
        company.do_not_contact = True
    else:
        profile.captcha_type = "CAPTCHA_RECAPTCHA"
    db.commit()
    result = auth.get(path).json()
    assert result["human_choice"]["state"] != "CURRENT"
    assert result["human_choice"]["active_destination"] is None
    assert auth.post(endpoint, json={**body, "expected_choice_version": 1}).status_code == 409
    assert not result["dm_ready"] and not result["execution_allowed"]


def test_expiry_and_immutable_ledger(auth, db):
    company, _, path, _, _, endpoint, body = ready(auth, db)
    assert auth.post(endpoint, json=body).status_code == 201
    row = db.scalar(select(DestinationChoiceEvent))
    purpose = db.scalar(select(DestinationReviewEvent))
    assert row.expires_at <= purpose.expires_at
    result = public_choice(db, company, [], now=row.expires_at)
    assert result["state"] == "EXPIRED" and result["active_destination"] is None
    for statement in [
        update(DestinationChoiceEvent).values(destination="changed"),
        delete(DestinationChoiceEvent),
        text("TRUNCATE destination_choice_events"),
    ]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(statement)
    module = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "migrations/versions/1ea563b6ad2d_human_preparation_destination_choice.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="evidence exists"):
            module["downgrade"]()
    db.delete(company)
    db.commit()
    assert db.scalar(select(func.count()).select_from(DestinationChoiceEvent)) == 1
    db.delete(db.get(Project, company.project_id))
    db.commit()
    assert db.scalar(select(func.count()).select_from(DestinationChoiceEvent)) == 0


def test_agent_viewer_other_project_and_extra_fields_rejected(auth, db, users):
    company, _, _, _, _, endpoint, body = ready(auth, db)
    assert (
        auth.post(
            endpoint, json=body, headers={"Authorization": "Bearer invalid-agent"}
        ).status_code
        == 403
    )
    for extra in ({"confirmed": True}, {"expires_at": "2099-01-01"}):
        assert auth.post(endpoint, json={**body, **extra}).status_code == 422
    assert auth.post(endpoint, json={**body, "expected_hash": "f" * 64}).status_code == 409
    assert auth.post(endpoint, json={**body, "expected_purpose_version": 2}).status_code == 409
    project = db.get(Project, company.project_id)
    project.user_id = users[1].id
    db.commit()
    assert auth.post(endpoint, json=body).status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.post(endpoint, json=body).status_code == 404


def test_choice_does_not_fallback_to_another_ready_destination(auth, db):
    company, _, path, _, _, endpoint, body = ready(auth, db)
    assert auth.post(endpoint, json=body).status_code == 201
    company.email = "unique@example.com"
    company.contact_quality_status = "verified"
    db.commit()
    assert (
        auth.post(
            f"/api/projects/{company.project_id}/lead-destinations/refresh", json={}
        ).status_code
        == 200
    )
    result = auth.get(path).json()
    email = next(d for d in result["destinations"] if d["type"] == "email")
    assert (
        auth.post(
            f"/api/companies/{company.id}/destinations/{email['id']}/reviews",
            json=dict(
                expected_hash=email["expected_hash"],
                expected_review_version=0,
                purpose="business",
                scope="location",
                source_url="https://shop.example/contact",
                evidence_excerpt="事業提携などのご相談はこちらで受け付けます。",
            ),
        ).status_code
        == 201
    )
    result = auth.get(path).json()
    assert any(d["status"] == "READY" for d in result["destinations"])
    assert result["human_choice"]["active_destination"] is None
    assert result["human_choice"]["state"] == "STALE"
    email = next(d for d in result["destinations"] if d["type"] == "email")
    assert (
        auth.post(
            f"/api/companies/{company.id}/destinations/{email['id']}/choice",
            json=dict(
                expected_hash=email["expected_hash"],
                expected_purpose_version=1,
                expected_choice_version=1,
            ),
        ).status_code
        == 201
    )
    result = auth.get(path).json()
    assert result["human_choice"]["active_destination"]["type"] == "email"
    assert result["human_choice"]["version"] == 2


@pytest.mark.parametrize("block", ["suppression", "unknown", "shared"])
def test_safety_changes_invalidate_choice_without_payload_change(auth, db, block):
    from app.models import Company, FormDelivery, OutreachDraft, SuppressionEntry
    from tests.test_location_import import import_locations

    company, profile, path, _, _, endpoint, body = ready(auth, db)
    assert auth.post(endpoint, json=body).status_code == 201
    if block == "suppression":
        db.add(
            SuppressionEntry(
                project_id=company.project_id, domain=company.domain, reason="synthetic only"
            )
        )
    elif block == "unknown":
        draft = OutreachDraft(company_id=company.id, channel="form", body="Synthetic history")
        db.add(draft)
        db.flush()
        db.add(
            FormDelivery(
                company_id=company.id,
                draft_id=draft.id,
                form_url=profile.form_url,
                status="unknown",
            )
        )
    else:
        import_locations(
            auth,
            {"id": str(company.project_id)},
            [["Second shop", "https://shop.example", "", "", "City 2-2", ""]],
        )
        other = db.scalar(select(Company).where(Company.id != company.id))
        other.contact_url = profile.form_url
    db.commit()
    result = auth.get(path).json()
    assert result["human_choice"]["state"] == "INELIGIBLE"
    assert result["human_choice"]["active_destination"] is None
    assert auth.post(endpoint, json={**body, "expected_choice_version": 1}).status_code == 409


def test_raw_insert_cannot_skip_version_or_human_membership(auth, db, users):
    company, _, _, _, _, endpoint, body = ready(auth, db)
    assert auth.post(endpoint, json=body).status_code == 201
    row = db.scalar(select(DestinationChoiceEvent))
    for actor, version, purpose_version in [
        (users[0].id, 3, 1),
        (users[1].id, 2, 1),
        (users[0].id, 2, 2),
    ]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(
                DestinationChoiceEvent(
                    project_id=row.project_id,
                    company_id=row.company_id,
                    destination_id=row.destination_id,
                    actor_user_id=actor,
                    version=version,
                    event_type="SELECTED",
                    destination_type=row.destination_type,
                    destination=row.destination,
                    snapshot_hash=row.snapshot_hash,
                    purpose_review_version=purpose_version,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                )
            )
            db.flush()
