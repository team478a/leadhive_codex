import runpy
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select

from app.config import settings
from app.models import (
    ApprovalRequest,
    Company,
    EmailDelivery,
    FormDelivery,
    OperationJob,
    OutreachDraft,
    Project,
    ProjectMember,
    SalesPreparationItem,
    SuppressionEntry,
)
from app.services import sales_preparation as service
from app.services.collection import Candidate
from app.services.scraper import FetchedPage, PageData
from tests.test_location_import import make_project


def companies(db, project, count=1, **values):
    rows = [
        Company(
            project_id=UUID(project["id"]),
            company_name=f"Example store {i}",
            source="csv",
            website_url=f"https://store{i}.example",
            domain=f"store{i}.example",
            email=f"sales@store{i}.example",
            analysis_status="completed",
            **values,
        )
        for i in range(count)
    ]
    db.add_all(rows)
    db.commit()
    return rows


def start(auth, project, **values):
    return auth.post(f"/api/projects/{project['id']}/sales-preparation", json=values)


@pytest.fixture
def providers(monkeypatch):
    counts = {"analysis": 0, "draft": 0}
    monkeypatch.setattr(settings, "openai_api_key", "test-only")
    monkeypatch.setattr(settings, "serper_api_key", "test-only")
    monkeypatch.setattr(settings, "outbound_enabled", False)

    def analyze(db, company, project, profile, force=False, usage_callback=None):
        assert force
        counts["analysis"] += 1
        company.ai_status, company.score, company.is_target = "completed", 88, True
        db.commit()

    def draft(context):
        counts["draft"] += 1
        return SimpleNamespace(
            subject=context.company_name, body=f"Draft for {context.company_name}"
        )

    monkeypatch.setattr(service, "analyze_company_ai", analyze)
    monkeypatch.setattr(
        service,
        "get_ai_provider",
        lambda: SimpleNamespace(name="test", model="test", generate_outreach=draft),
    )
    monkeypatch.setattr(service, "search_serper", lambda *args: pytest.fail("Unexpected search"))
    return counts


def execute(db, response, stop=lambda *args: False):
    assert response.status_code == 202, response.text
    job = db.get(OperationJob, UUID(response.json()["id"]))
    job.status = "running"
    db.commit()
    service.run_preparation(db, job, job.worker_id, stop)
    return job


def test_300_individual_drafts_without_any_send(auth, db, providers):
    project = make_project(auth)
    companies(db, project, 300)
    job = execute(db, start(auth, project, max_ai_requests=600))
    assert job.total_count == job.processed_count == job.success_count == 300
    assert providers == {"analysis": 300, "draft": 300}
    assert job.payload["used_ai_requests"] == 600
    assert db.scalar(select(func.count()).select_from(OutreachDraft)) == 300
    assert (
        db.scalar(
            select(func.count())
            .select_from(SalesPreparationItem)
            .where(SalesPreparationItem.status == "ready")
        )
        == 300
    )
    for model in (EmailDelivery, FormDelivery, ApprovalRequest):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    # Recovery after all items committed restores counters without new provider calls.
    job.processed_count = job.success_count = 0
    db.commit()
    service.run_preparation(db, job, None, lambda *args: False)
    assert job.processed_count == 300 and providers["draft"] == 300


def test_budget_and_durable_resume(auth, db, providers):
    project = make_project(auth)
    companies(db, project, 4)
    response = start(auth, project, max_ai_requests=5)

    def stop(db, job, worker):
        return (
            db.scalar(
                select(func.count())
                .select_from(SalesPreparationItem)
                .where(SalesPreparationItem.draft_id.is_not(None))
            )
            >= 1
        )

    job = execute(db, response, stop)
    assert providers == {"analysis": 1, "draft": 1}
    job.status = "cancelled"
    db.commit()
    resumed = auth.post(f"/api/sales-preparation/{job.id}/resume")
    execute(db, resumed)
    assert job.payload["used_ai_requests"] == 5
    assert providers == {"analysis": 3, "draft": 2}
    assert job.processed_count == 4
    assert db.scalar(select(func.count()).select_from(OutreachDraft)) == 2
    assert auth.post(f"/api/sales-preparation/{job.id}/resume").status_code == 409


def test_pending_recovery_does_not_repeat_unknown_ai(auth, db, providers):
    project = make_project(auth)
    companies(db, project)
    response = start(auth, project)
    item = db.scalar(select(SalesPreparationItem))
    item.status, item.details = "running", {"analysis_started": True}
    db.commit()
    execute(db, response)
    assert item.status == "review" and providers["analysis"] == 0


def test_suppression_blocks_before_provider(auth, db, providers):
    project = make_project(auth)
    row = companies(db, project)[0]
    db.add(SuppressionEntry(project_id=row.project_id, domain=row.domain, reason="opt-out"))
    db.commit()
    execute(db, start(auth, project))
    assert db.scalar(select(SalesPreparationItem)).status == "blocked"
    assert providers == {"analysis": 0, "draft": 0}


def test_purpose_change_stops_old_preparation(auth, db, providers):
    project = make_project(auth)
    companies(db, project)
    response = start(auth, project)
    db.get(Project, UUID(project["id"])).sales_objective = "Changed offer"
    db.commit()
    execute(db, response)
    assert db.scalar(select(SalesPreparationItem)).status == "review"
    assert providers["analysis"] == 0


def test_limits_concurrent_and_send_fields_rejected(auth, db):
    project = make_project(auth)
    companies(db, project)
    for body in (
        {"limit": 301},
        {"max_ai_requests": 601},
        {"confirmed": True},
        {"send": True},
        {"company_ids": [str(UUID(int=10))]},
    ):
        assert start(auth, project, **body).status_code == 422
    assert start(auth, project).status_code == 202
    assert start(auth, project).status_code == 409
    assert (
        auth.post(
            f"/api/projects/{project['id']}/operations",
            json={
                "operation_type": "ai_analysis",
                "company_ids": [],
                "force": False,
            },
        ).status_code
        == 409
    )


def test_viewer_and_other_project_denied(auth, db, users):
    project = make_project(auth)
    companies(db, project)
    db.add(ProjectMember(project_id=UUID(project["id"]), user_id=users[1].id, role="viewer"))
    db.commit()
    from tests.conftest import PASSWORD

    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert start(auth, project).status_code == 404
    assert auth.get(f"/api/projects/{project['id']}/sales-preparation").status_code == 200
    assert auth.get(f"/api/projects/{UUID(int=10)}/sales-preparation").status_code == 404


def test_worker_claim_with_outbound_disabled(auth, db, providers, monkeypatch):
    from app import worker

    project = make_project(auth)
    companies(db, project)
    response = start(auth, project)
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(worker, "apply_application_settings", lambda db: None)
    assert worker.run_once()
    job = db.get(OperationJob, UUID(response.json()["id"]))
    assert job.status == "completed" and job.processed_count == 1
    assert providers == {"analysis": 1, "draft": 1}


def test_agent_cannot_start_or_read_preparation(auth, db):
    project = make_project(auth)
    companies(db, project)
    token = auth.post(
        f"/api/projects/{project['id']}/agents",
        json={
            "name": "Preparation test",
            "scopes": ["outreach:prepare", "outreach:read"],
        },
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/api/projects/{project['id']}/sales-preparation"
    assert auth.post(path, json={}, headers=headers).status_code == 403
    auth.cookies.clear()
    assert auth.get(path, headers=headers).status_code == 403


@pytest.mark.parametrize("contact_url", ["", "https://store0.example/contact"])
def test_form_preparation_disables_ai_fallback(auth, db, providers, monkeypatch, contact_url):
    project = make_project(auth)
    row = companies(db, project)[0]
    row.email, row.contact_url = "", contact_url
    db.commit()
    calls = []
    monkeypatch.setattr(
        service, "analyze_company_forms", lambda db, company, **args: calls.append(args)
    )
    execute(db, start(auth, project, channel="form"))
    assert calls == [{"allow_ai": False}]
    assert db.scalar(select(SalesPreparationItem)).status == "review"
    assert providers == {"analysis": 1, "draft": 0}


@pytest.mark.parametrize(
    ("markup", "expected_status"),
    [
        ("", "ready"),
        ("営業目的の問い合わせは禁止です。", "blocked"),
        ('<div class="g-recaptcha"></div>', "review"),
    ],
)
def test_missing_contact_url_runs_bounded_form_discovery_without_send(
    auth, db, providers, monkeypatch, markup, expected_status
):
    from app.models import FormProfile
    from tests.test_form_intelligence import install_pages

    project = make_project(auth)
    row = companies(db, project)[0]
    row.email, row.contact_url = "", ""
    db.commit()
    install_pages(
        monkeypatch,
        {
            row.website_url: "<html>Company home</html>",
            f"{row.website_url}/contact": (
                f'<html>{markup}<form method="post">'
                '<input name="email" type="email" required>'
                '<textarea name="message" required></textarea>'
                '<button type="submit">送信</button></form></html>'
            ),
        },
    )
    execute(db, start(auth, project, channel="form", max_search_requests=0))
    item = db.scalar(select(SalesPreparationItem))
    assert item.status == expected_status
    assert item.details["form_checked"] is True
    assert db.scalar(select(FormProfile).where(FormProfile.form_found.is_(True))) is not None
    draft_count = 1 if expected_status == "ready" else 0
    assert providers == {"analysis": 1, "draft": draft_count}
    assert db.scalar(select(func.count()).select_from(OutreachDraft)) == draft_count
    for model in (EmailDelivery, FormDelivery, ApprovalRequest):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("matches", [False, True])
def test_site_match_requires_address_or_phone(auth, db, providers, monkeypatch, matches):
    project = make_project(auth)
    row = companies(db, project, address="City 12-3")[0]
    row.website_url, row.domain, row.analysis_status = None, "", "pending"
    db.commit()
    monkeypatch.setattr(
        service,
        "search_serper",
        lambda *args: [
            Candidate(company_name=row.company_name, website_url="https://official.example")
        ],
    )
    monkeypatch.setattr(
        service,
        "scrape_company",
        lambda url: (
            FetchedPage(url, ""),
            PageData(website_text=f"{row.company_name} City {'12-3' if matches else '99'}"),
        ),
    )

    def web(db, company):
        company.analysis_status = "completed"
        db.commit()

    monkeypatch.setattr(service, "analyze", web)
    job = execute(db, start(auth, project))
    item = db.scalar(select(SalesPreparationItem))
    assert job.payload["used_search_requests"] == (1 if matches else 2)
    assert item.details["website_candidates"][0]["url"] == "https://official.example"
    assert item.status == ("ready" if matches else "review")
    assert bool(row.website_url) == matches


def test_migration_preserves_preparation_history(auth, db):
    project = make_project(auth)
    companies(db, project)
    assert start(auth, project).status_code == 202
    migration = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "migrations/versions/e3b7d92f410a_add_sales_preparation.py"
        )
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="Preparation jobs exist"):
            migration["downgrade"]()
    assert db.scalar(select(func.count()).select_from(SalesPreparationItem)) == 1


def test_offset_and_explicit_selection(auth, db):
    project = make_project(auth)
    rows = companies(db, project, 4)
    response = start(auth, project, offset=3, limit=1)
    assert response.status_code == 202 and response.json()["total_count"] == 1
    item = db.scalar(select(SalesPreparationItem))
    expected = db.scalar(
        select(Company.id)
        .where(Company.project_id == UUID(project["id"]))
        .order_by(Company.created_at, Company.id)
        .offset(3)
        .limit(1)
    )
    assert item.company_id == expected
    auth.post(f"/api/operations/{response.json()['id']}/cancel")
    assert start(auth, project, offset=1, company_ids=[str(rows[0].id)]).status_code == 422
    assert start(auth, project, company_ids=[str(rows[0].id)]).status_code == 202
