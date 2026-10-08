"""Fixed-cohort paged diagnostics; synthetic data, no dispatch or external I/O."""

from uuid import UUID

from sqlalchemy import func, select

from app.models import (
    ApprovalRequest,
    Company,
    EmailDelivery,
    FormDelivery,
    LeadSiteEvidence,
    Project,
    ProjectMember,
)
from app.services.lead_identity import identity_hash
from app.services.sendability import evaluate
from tests.test_completion_metrics import fixture_cohort
from tests.test_location_import import import_locations
from tests.test_sendability import profile_fixture


def test_paged_diagnostics_match_single_lead_and_deduplicate_shared_keys(auth, db):
    project, companies, cohort = fixture_cohort(auth, db)
    for index, company in enumerate(companies):
        url = (
            "https://chain.example/contact" if index < 2 else "https://chain.example/store3/contact"
        )
        company.contact_url = url
        profile_fixture(db, company, form_url=url)
        db.add(
            LeadSiteEvidence(
                company_id=company.id,
                source_url=company.website_url,
                identity_hash=identity_hash(company),
                confidence="CONFIRMED",
                reasons=["NAME_MATCH", "ADDRESS_MATCH"],
            )
        )
    db.commit()
    auth.post(f"/api/projects/{project['id']}/lead-destinations/refresh", json={})
    for company in companies:
        item = auth.get(f"/api/companies/{company.id}/sendability").json()["destinations"][0]
        response = auth.post(
            f"/api/companies/{company.id}/destinations/{item['id']}/reviews",
            json=dict(
                expected_hash=item["expected_hash"],
                expected_review_version=0,
                purpose="business",
                scope="location",
                source_url=company.contact_url,
                evidence_excerpt="事業のご相談を受け付ける窓口と確認しました。",
            ),
        )
        assert response.status_code == 201
    base = f"/api/completion-cohorts/{cohort['id']}/destination-diagnostics"
    rows = []
    context = None
    for offset in range(3):
        page = auth.get(
            base,
            params={
                "offset": offset,
                "limit": 1,
                **({"expected_context_hash": context} if context else {}),
            },
        ).json()
        assert page["discovered"] == 3 and page["inspected"] == 1
        assert page["next_offset"] == (offset + 1 if offset < 2 else None)
        assert page["dm_ready_rate"] is None and not page["execution_allowed"]
        context = page["context_hash"]
        rows.extend(page["rows"])
    keys = []
    for row in rows:
        company = db.get(Company, UUID(row["company_id"]))
        single = evaluate(db, company)
        assert row["company_name"] == company.company_name
        assert row["status"] == single["status"]
        assert {r["code"] for r in row["reasons"]} == {r["code"] for r in single["reasons"]}
        keys.extend(d["key"] for d in row["destinations"])
    assert len(keys) == 3 and len(set(keys)) == 2
    assert sum(row["status"] == "READY" for row in rows) == 1
    assert sum(d["shared"] for row in rows for d in row["destinations"]) == 2
    for model in (ApprovalRequest, EmailDelivery, FormDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_fixed_membership_missing_leads_limits_context_and_reader_boundary(auth, db, users):
    project, companies, cohort = fixture_cohort(auth, db, count=2)
    path = f"/api/completion-cohorts/{cohort['id']}/destination-diagnostics"
    first = auth.get(path, params={"limit": 1}).json()
    # Cohort creation response omits IDs; use server-owned fixed membership.
    from app.models import LeadCompletionCohort

    fixed = db.get(LeadCompletionCohort, UUID(cohort["id"]))
    removed = db.get(Company, UUID(fixed.company_ids[1]))
    db.delete(removed)
    db.commit()
    import_locations(auth, project, [["New shop", "https://new.example", "", "", "City 4-1", ""]])
    second = auth.get(
        path, params={"offset": 1, "limit": 1, "expected_context_hash": first["context_hash"]}
    ).json()
    assert second["discovered"] == 2 and second["next_offset"] is None
    assert second["rows"][0]["status"] == "HOLD"
    assert second["rows"][0]["reasons"][0]["code"] == "LEAD_REMOVED_OR_MERGED"
    assert second["rows"][0]["destinations"] == []
    assert second["rows"][0]["company_name"] is None
    for params in [
        {"limit": 51},
        {"limit": 0},
        {"offset": -1},
        {"offset": 3},
        {"expected_context_hash": "bad"},
    ]:
        assert auth.get(path, params=params).status_code == 422
    owner = db.get(Project, UUID(project["id"]))
    owner.sales_objective = "Changed objective"
    db.commit()
    assert (
        auth.get(path, params={"expected_context_hash": first["context_hash"]}).status_code == 409
    )
    assert auth.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 403
    owner.user_id = users[1].id
    db.commit()
    assert auth.get(path).status_code == 404
    db.add(ProjectMember(project_id=owner.id, user_id=users[0].id, role="viewer"))
    db.commit()
    assert auth.get(path).status_code == 200
