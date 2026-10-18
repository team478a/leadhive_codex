from datetime import datetime, timezone

from sqlalchemy import event

from app.database import engine
from app.models import (
    Company,
    FormDmReadinessResult,
    FormProfile,
    OperationJob,
    SalesPreparationItem,
)
from tests.test_approval_foundation import workspace as workspace


def seed_large_project(db, workspace):
    project, existing_company = workspace
    companies = [
        Company(
            project_id=project.id,
            company_name=f"Query bound company {index:04d}",
            source="csv",
            website_url=f"https://company-{index}.example",
            domain=f"company-{index}.example",
        )
        for index in range(1, 3000)
    ]
    companies.insert(0, existing_company)
    db.add_all(companies[1:])
    db.flush()
    profiles = [
        FormProfile(
            company_id=company.id,
            form_url=f"https://company-{index}.example/contact",
            is_primary=True,
            form_found=True,
            fingerprint="a" * 64,
            form_status="REVIEW_REQUIRED",
        )
        for index, company in enumerate(companies, 1)
    ]
    db.add_all(profiles)
    readiness_job = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="completed",
        total_count=3000,
        processed_count=3000,
        success_count=3000,
        finished_at=datetime.now(timezone.utc),
    )
    sales_job = OperationJob(
        project_id=project.id,
        operation_type="prepare_outreach",
        status="completed",
        payload={
            "used_search_requests": 0,
            "used_ai_requests": 0,
            "max_search_requests": 0,
            "max_ai_requests": 0,
        },
        total_count=3000,
        processed_count=3000,
        finished_at=datetime.now(timezone.utc),
    )
    db.add_all((readiness_job, sales_job))
    db.flush()
    db.add_all(
        [
            FormDmReadinessResult(
                job_id=readiness_job.id,
                company_id=company.id,
                profile_id=profile.id,
                primary_reason="NEEDS_MAPPING_REVIEW",
                secondary_reasons=[],
                review_queue_eligible=True,
            )
            for company, profile in zip(companies, profiles, strict=True)
        ]
    )
    db.add_all(
        [SalesPreparationItem(job_id=sales_job.id, company_id=company.id) for company in companies]
    )
    db.commit()
    return project, sales_job


def count_sql(statements, conn, cursor, statement, parameters, context, executemany):
    if statement.lstrip().upper().startswith(("SELECT", "WITH")):
        statements.append(statement)


def request_with_sql_limit(client, path, maximum):
    statements = []

    def listener(*args):
        count_sql(statements, *args)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        response = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert response.status_code == 200, response.text
    assert len(statements) <= maximum, f"{len(statements)} SELECTs exceeded {maximum}"
    return response


def test_large_project_preparation_apis_have_bounded_select_counts(auth, db, workspace):
    project, sales_job = seed_large_project(db, workspace)

    readiness = request_with_sql_limit(
        auth, f"/api/projects/{project.id}/form-dm-readiness", maximum=9
    )
    assert len(readiness.json()["items"]) == 20

    queue = request_with_sql_limit(
        auth, f"/api/projects/{project.id}/form-review-queue", maximum=160
    )
    assert len(queue.json()["items"]) == 20

    summaries = request_with_sql_limit(
        auth, f"/api/projects/{project.id}/sales-preparation", maximum=5
    )
    assert "items" not in summaries.json()[0]
    assert summaries.json()[0]["item_count"] == 3000

    details = request_with_sql_limit(
        auth, f"/api/sales-preparation/{sales_job.id}/items?offset=0&limit=20", maximum=5
    )
    assert len(details.json()["items"]) == 20
    assert details.json()["total"] == 3000
