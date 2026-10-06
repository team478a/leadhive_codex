"""Human observed evidence templates, no provider or dispatch execution."""

import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.models import (
    ApprovalRequest,
    EmailDelivery,
    FormDelivery,
    LeadDmPreparation,
    OutreachDraft,
    OutreachTemplate,
    Project,
    ProjectMember,
)
from tests.test_destination_choice import ready


def preparation_fixture(auth, db):
    company, profile, _, _, _, choice_path, choice_body = ready(auth, db)
    assert auth.post(choice_path, json=choice_body).status_code == 201
    response = auth.post(
        f"/api/projects/{company.project_id}/outreach-templates",
        json=dict(
            name="Synthetic service",
            channel="form",
            subject="",
            body=(
                "{{company_name}} ご担当者様\n{{personalization}}\n"
                "Synthetic service proposal and signature"
            ),
        ),
    )
    assert response.status_code == 201
    endpoint = f"/api/companies/{company.id}/dm-preparation"
    options = auth.get(endpoint).json()
    template = options["templates"][0]
    body = dict(
        template_id=template["id"],
        expected_template_hash=template["hash"],
        expected_context_hash=options["context_hash"],
        expected_destination_hash=options["human_choice"]["active_destination"]["payload_hash"],
        expected_choice_version=1,
        source_url="https://shop.example/services",
        fact="公開のサービス紹介を掲載しています",
        evidence_excerpt="当社は公開のサービス紹介を掲載しています。",
        fact_observed=True,
    )
    return company, profile, endpoint, body


def test_template_evidence_snapshot_and_no_send_side_effects(auth, db):
    company, _, endpoint, body = preparation_fixture(auth, db)
    response = auth.post(endpoint, json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "DRAFT_PREPARED"
    assert result["snapshot"]["company_name"] == company.company_name
    assert result["snapshot"]["destination"]["destination"] == "https://shop.example/contact"
    assert body["fact"] in result["snapshot"]["body"]
    assert result["snapshot"]["evidence"]["source_url"] == body["source_url"]
    assert result["snapshot"]["evidence"]["confidence"] == "HUMAN_OBSERVED"
    assert not result["dm_ready"] and not result["execution_allowed"]
    assert auth.get(endpoint).json()["preparations"][0]["id"] == result["id"]
    for model in (ApprovalRequest, OutreachDraft, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "change,reason",
    [
        ("template", "TEMPLATE_CHANGED"),
        ("objective", "SALES_CONTEXT_CHANGED"),
        ("ban", "DESTINATION_CHOICE_CHANGED"),
        ("choice", "DESTINATION_CHOICE_CHANGED"),
        ("fingerprint", "DESTINATION_CHOICE_CHANGED"),
    ],
)
def test_preparation_requires_review_after_changed_dependencies(auth, db, change, reason):
    company, profile, endpoint, body = preparation_fixture(auth, db)
    assert auth.post(endpoint, json=body).status_code == 201
    if change == "template":
        db.scalar(select(OutreachTemplate)).body = "Changed template"
    elif change == "objective":
        db.get(Project, company.project_id).sales_objective = "Changed objective"
    elif change == "ban":
        company.do_not_contact = True
    elif change == "choice":
        assert (
            auth.post(
                f"/api/companies/{company.id}/destination-choice/revoke",
                json={"expected_choice_version": 1},
            ).status_code
            == 201
        )
    else:
        profile.fingerprint = "a" * 64
    db.commit()
    result = auth.get(endpoint).json()["preparations"][0]
    assert result["status"] == "REVIEW" and result["reason"] == reason
    assert auth.post(endpoint, json=body).status_code == 409
    assert not result["dm_ready"]


def test_unsafe_evidence_unknown_placeholders_and_stale_input_rejected(auth, db):
    _, _, endpoint, body = preparation_fixture(auth, db)
    for source in [
        "http://localhost/contact",
        "https://other.example/about",
        "https://user:secret@shop.example/services",
        "https://shop.example/services?token=secret",
    ]:
        assert auth.post(endpoint, json={**body, "source_url": source}).status_code == 422
    for extra in [
        {"fact_observed": False},
        {"confirmed": True},
        {"expires_at": "2099-01-01"},
        {"fact": "根拠の引用に含まれていない内容"},
    ]:
        assert auth.post(endpoint, json={**body, **extra}).status_code == 422
    for extra in [
        {"expected_template_hash": "f" * 64},
        {"expected_context_hash": "f" * 64},
        {"expected_destination_hash": "f" * 64},
        {"expected_choice_version": 2},
    ]:
        assert auth.post(endpoint, json={**body, **extra}).status_code == 409
    template = db.scalar(select(OutreachTemplate))
    template.body = "{{personalization}} {{secret_key}}"
    db.commit()
    body["expected_template_hash"] = auth.get(endpoint).json()["templates"][0]["hash"]
    assert auth.post(endpoint, json=body).status_code == 422


def test_viewer_other_project_agent_and_immutable_history(auth, db, users):
    company, _, endpoint, body = preparation_fixture(auth, db)
    assert (
        auth.post(
            endpoint, json=body, headers={"Authorization": "Bearer invalid-agent"}
        ).status_code
        == 403
    )
    assert auth.post(endpoint, json=body).status_code == 201
    for statement in [
        update(LeadDmPreparation).values(snapshot={}),
        delete(LeadDmPreparation),
        text("TRUNCATE lead_dm_preparations"),
    ]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(statement)
    module = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "migrations/versions/37945a503231_evidence_bound_dm_template_preparation.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="evidence exists"):
            module["downgrade"]()
    project = db.get(Project, company.project_id)
    project.user_id = users[1].id
    db.commit()
    assert auth.get(endpoint).status_code == 404
    assert auth.post(endpoint, json=body).status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(endpoint).json()["can_prepare"] is False
    assert auth.post(endpoint, json=body).status_code == 404
    db.delete(company)
    db.commit()
    assert db.scalar(select(func.count()).select_from(LeadDmPreparation)) == 1
    db.delete(project)
    db.commit()
    assert db.scalar(select(func.count()).select_from(LeadDmPreparation)) == 0


def test_source_text_is_data_not_recursively_rendered(auth, db):
    _, _, endpoint, body = preparation_fixture(auth, db)
    fact = "{{company_name}}という文字列が公開されています"
    body.update(fact=fact, evidence_excerpt=fact)
    result = auth.post(endpoint, json=body)
    assert result.status_code == 201
    assert fact in result.json()["snapshot"]["body"]


def test_foreign_template_and_anonymous_requests_rejected(auth, db):
    from tests.test_location_import import make_project

    _, _, endpoint, body = preparation_fixture(auth, db)
    project = make_project(auth)
    template = auth.post(
        f"/api/projects/{project['id']}/outreach-templates",
        json=dict(
            name="Foreign template", channel="form", subject="", body="{{personalization}} Proposal"
        ),
    )
    assert template.status_code == 201
    assert (
        auth.post(endpoint, json={**body, "template_id": template.json()["id"]}).status_code == 404
    )
    auth.cookies.clear()
    assert auth.get(endpoint).status_code == 401
    assert auth.post(endpoint, json=body).status_code == 401
    assert (
        auth.post(
            endpoint, json=body, headers={"Authorization": "Bearer invalid-agent"}
        ).status_code
        == 403
    )
