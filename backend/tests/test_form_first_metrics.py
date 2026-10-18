from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import event

from app.database import engine
from app.models import (
    CollectionDiscoveryHit,
    Company,
    FormDmReadinessResult,
    FormProfile,
    LeadProcessingUsage,
    OperationJob,
)
from tests.test_collection import make_project


def test_discovery_metrics_use_bounded_sql_aggregates_for_large_projects(auth, db):
    project_id = UUID(make_project(auth)["id"])
    companies = [
        Company(
            project_id=project_id,
            company_name=f"株式会社指標{i}",
            website_url=f"https://metric-{i}.test/",
            domain=f"metric-{i}.test",
            source="serper",
        )
        for i in range(3000)
    ]
    db.add_all(companies)
    operation = OperationJob(
        project_id=project_id,
        operation_type="collect_search",
        status="completed",
        payload={
            "collection_method": "form_first",
            "form_first_query_map": {
                "intitle:お問い合わせ 工務店": {"query_type": "intitle_contact"}
            },
        },
    )
    readiness_job = OperationJob(
        project_id=project_id,
        operation_type="form_dm_readiness",
        status="completed",
        finished_at=datetime.now(timezone.utc),
        payload={},
    )
    db.add_all([operation, readiness_job])
    db.flush()

    from app.services.collection_jobs import start_job

    collection = start_job(
        db,
        project_id,
        "serper",
        "intitle:お問い合わせ 工務店",
        "東京都",
        operation_job_id=operation.id,
    )
    collection.discovery_summary = {"received_count": 50, "captured_count": 50}
    profile = FormProfile(
        company_id=companies[0].id,
        form_url="https://metric-0.test/contact",
        form_status="READY",
        sales_contact_status="ALLOWED",
        form_found=True,
        delivery_supported=True,
        fingerprint="a" * 64,
    )
    db.add(profile)
    db.flush()
    db.add(
        FormDmReadinessResult(
            job_id=readiness_job.id,
            company_id=companies[0].id,
            profile_id=profile.id,
            primary_reason="READY",
            secondary_reasons=[],
            review_queue_eligible=False,
        )
    )
    observed_at = datetime.now(timezone.utc)
    db.add_all(
        LeadProcessingUsage(
            project_id=project_id,
            collection_job_id=collection.id,
            kind="search",
            provider="serper",
            status="completed",
            started_at=observed_at,
            elapsed_ms=100,
        )
        for _ in range(3)
    )
    hits = []
    for index in range(50):
        query_type = "intitle_contact" if index < 40 else "inurl_contact"
        candidate = index % 4 == 0 if index < 40 else index == 40
        hits.append(
            CollectionDiscoveryHit(
                collection_job_id=collection.id,
                position=index + 1,
                snapshot={
                    "form_first_query_type": query_type,
                    "form_first_candidate": candidate,
                    "form_first_form_status": "FORM_FOUND" if index < 30 else "NO_FORM_ON_PAGE",
                    "form_first_corporate_check": "CORPORATE_NUMBER_NOT_FOUND",
                    "form_first_existing_url_added": index == 0,
                },
                raw_hash=f"{index:064x}",
                classification="FORM_FIRST",
                classification_reason="FORM_FOUND" if index < 30 else "NO_FORM_ON_PAGE",
                disposition="SAVED",
                company_id=companies[index].id,
                retain_until=observed_at + timedelta(days=30),
            )
        )
    db.add_all(hits)
    db.commit()

    statements = []

    def count_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        response = auth.get(f"/api/collection-jobs/{collection.id}/discovery?offset=0&limit=20")
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert response.status_code == 200
    summary = response.json()["summary"]
    metrics = summary["metrics"]
    assert len(statements) <= 12
    assert not any("companies" in statement.lower() for statement in statements)
    assert metrics["search_request_count"] == 3
    assert metrics["contact_page_candidate_count"] == 11
    assert metrics["form_found_count"] == 30
    assert metrics["newly_registered_company_count"] == 50
    assert metrics["existing_contact_url_added_company_count"] == 1
    assert metrics["corporate_checks"]["NOT_FOUND"] == 50
    assert metrics["sendable_company_count"] == 1
    assert metrics["sendable_companies_per_100_searches"] == 33.3
    assert metrics["query_types"]["intitle_contact"]["candidate_rate_percent"] == 25.0
    assert metrics["query_types"]["inurl_contact"]["low_effect"] is True
