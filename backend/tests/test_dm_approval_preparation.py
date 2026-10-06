"""Synthetic C2 handoff tests; never dispatch or contact external services."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    EmailDelivery,
    FormDelivery,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    OutreachTemplate,
    Project,
    ProjectMember,
)
from tests.test_approval_foundation import approve, challenge
from tests.test_destination_review import reviewed_fixture


def prepared(auth, db):
    company, profile, path, review_path, review = reviewed_fixture(auth, db)
    profile.action_url = "https://shop.example/submit"
    profile.confirmation_page = False
    field = db.scalar(
        select(FormProfileField).where(FormProfileField.form_profile_id == profile.id)
    )
    field.name = "message"
    field.required = True
    db.add(FormSenderSettings(id=1, contact_name="Synthetic sender", email="sender@example.com"))
    db.commit()
    review["expected_hash"] = auth.get(path).json()["destinations"][0]["expected_hash"]
    assert auth.post(review_path, json=review).status_code == 201
    dest = auth.get(path).json()["destinations"][0]
    assert (
        auth.post(
            f"/api/companies/{company.id}/destinations/{dest['id']}/choice",
            json=dict(
                expected_hash=dest["expected_hash"],
                expected_purpose_version=dest["review"]["version"],
                expected_choice_version=0,
            ),
        ).status_code
        == 201
    )
    template = auth.post(
        f"/api/projects/{company.project_id}/outreach-templates",
        json=dict(
            name="Synthetic template",
            channel="form",
            subject="",
            body="{{company_name}} {{personalization}} Synthetic service proposal",
        ),
    ).json()
    endpoint = f"/api/companies/{company.id}/dm-preparation"
    opts = auth.get(endpoint).json()
    body = dict(
        template_id=template["id"],
        expected_template_hash=opts["templates"][0]["hash"],
        expected_context_hash=opts["context_hash"],
        expected_destination_hash=opts["human_choice"]["active_destination"]["payload_hash"],
        expected_choice_version=1,
        source_url="https://shop.example/services",
        fact="公開のサービス紹介を掲載しています",
        evidence_excerpt="当社は公開のサービス紹介を掲載しています。",
        fact_observed=True,
    )
    result = auth.post(endpoint, json=body)
    assert result.status_code == 201, result.text
    return company, profile, f"/api/dm-preparations/{result.json()['id']}", endpoint, body


def pending(auth, path):
    preview = auth.get(path + "/approval-preview").json()
    assert preview["status"] == "READY_TO_PREPARE", preview
    response = auth.post(
        path + "/approval-request", json={"expected_preparation_hash": preview["preparation_hash"]}
    )
    assert response.status_code == 201, response.text
    return response.json(), preview


def test_pending_fixed_values_idempotence_and_human_stepup(auth, db):
    company, _, path, _, _ = prepared(auth, db)
    item, preview = pending(auth, path)
    assert item["status"] == "PENDING"
    assert preview["proposal"]["field_values"]["message"] == preview["proposal"]["body"]
    assert item["lead_dm_evidence"]["evidence"]["confidence"] == "HUMAN_OBSERVED"
    again = auth.post(
        path + "/approval-request", json={"expected_preparation_hash": preview["preparation_hash"]}
    )
    assert again.json()["id"] == item["id"]
    ready = auth.get(path + "/approval-preview").json()
    assert ready["dm_ready"] and not ready["execution_allowed"]
    assert db.scalar(select(func.count()).select_from(OutreachDraft)) == 1
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == 1
    for model in (EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert approve(auth, item, "invalid-token").status_code in (403, 422)
    response = approve(auth, item, challenge(auth, item))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"
    assert (
        auth.put(
            f"/api/outreach-drafts/{item['source_draft_id']}",
            json={"subject": "changed", "body": "changed"},
        ).status_code
        == 409
    )
    assert auth.delete(f"/api/outreach-drafts/{item['source_draft_id']}").status_code == 409


@pytest.mark.parametrize("change", ["sender", "template", "ban", "fingerprint", "new_fact"])
def test_changed_dependencies_invalidate_approval(auth, db, change):
    company, profile, path, endpoint, body = prepared(auth, db)
    item, _ = pending(auth, path)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    if change == "sender":
        db.get(FormSenderSettings, 1).contact_name = "Changed sender"
    elif change == "template":
        db.scalar(select(OutreachTemplate)).body = "Changed"
    elif change == "ban":
        company.do_not_contact = True
    elif change == "fingerprint":
        profile.fingerprint = "a" * 64
    else:
        body.update(
            fact="新しい公開サービス紹介を掲載しています",
            evidence_excerpt="新しい公開サービス紹介を掲載しています",
        )
        assert auth.post(endpoint, json=body).status_code == 201
    db.commit()
    assert not auth.get(path + "/approval-preview").json()["dm_ready"]
    response = auth.get(f"/api/approval-requests/{item['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REVOKED"


def test_stale_inputs_and_principal_guards(auth, db, users):
    company, _, path, _, _ = prepared(auth, db)
    preview = auth.get(path + "/approval-preview").json()
    data = {"expected_preparation_hash": preview["preparation_hash"]}
    assert (
        auth.post(path + "/approval-request", json={**data, "confirmed": True}).status_code == 422
    )
    assert (
        auth.post(
            path + "/approval-request", json={"expected_preparation_hash": "f" * 64}
        ).status_code
        == 409
    )
    assert (
        auth.post(
            path + "/approval-request", json=data, headers={"Authorization": "Bearer agent"}
        ).status_code
        == 403
    )
    project = db.get(Project, company.project_id)
    project.user_id = users[1].id
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(path + "/approval-preview").status_code == 200
    assert auth.post(path + "/approval-request", json=data).status_code == 404


def test_missing_sender_and_unknown_form_stage_hold(auth, db):
    _, profile, path, _, _ = prepared(auth, db)
    profile.confirmation_page = None
    db.commit()
    result = auth.get(path + "/approval-preview").json()
    assert result["status"] == "HOLD" and not result["dm_ready"]
    profile.confirmation_page = False
    db.get(FormSenderSettings, 1).email = ""
    db.commit()
    assert auth.get(path + "/approval-preview").json()["status"] == "HOLD"


def test_expiration_does_not_dispatch(auth, db, monkeypatch):
    _, _, path, _, _ = prepared(auth, db)
    item, _ = pending(auth, path)
    request = db.scalar(select(ApprovalRequest))
    assert request.expires_at <= datetime.now(timezone.utc) + timedelta(hours=24)
    # Request expiry is immutable; test clock through read-only service instead.
    from app.services import dm_approval_preparation as service

    assert service.valid_request(db, request)
    from app.services import human_approval

    monkeypatch.setattr(human_approval, "now", lambda: request.expires_at + timedelta(seconds=1))
    response = auth.get(f"/api/approval-requests/{item['id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "EXPIRED"
    assert not auth.get(path + "/approval-preview").json()["dm_ready"]
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0


def test_bound_draft_cannot_be_reproposed_without_evidence(auth, db):
    company, _, path, _, _ = prepared(auth, db)
    item, preview = pending(auth, path)
    data = preview["proposal"] | {"source_draft_id": item["source_draft_id"]}
    response = auth.post(f"/api/projects/{company.project_id}/approval-requests", json=data)
    assert response.status_code == 409, response.text
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == 1


def test_paged_dm_ready_is_current_readonly_and_not_candidate_ready(auth, db):
    company, _, path, _, _ = prepared(auth, db)
    pending(auth, path)
    from app.services.dm_approval_preparation import readiness

    project = db.get(Project, company.project_id)
    assert readiness(db, company, project)["dm_ready"]
    cohort = auth.post(
        f"/api/projects/{project.id}/completion-cohorts", json={"name": "Synthetic C2 list"}
    )
    assert cohort.status_code == 201
    diagnostic = f"/api/completion-cohorts/{cohort.json()['id']}/destination-diagnostics"
    page = auth.get(diagnostic).json()
    assert page["discovered"] == 1 and page["rows"][0]["dm_ready"]
    assert page["dm_ready_rate"] is None and not page["execution_allowed"]
    db.get(FormSenderSettings, 1).contact_name = "Changed"
    db.commit()
    assert not readiness(db, company, project)["dm_ready"]
    assert not auth.get(diagnostic).json()["rows"][0]["dm_ready"]
    assert db.scalar(select(ApprovalRequest)).status == "PENDING"
