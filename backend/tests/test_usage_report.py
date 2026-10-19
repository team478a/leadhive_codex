from uuid import UUID

from sqlalchemy import event

from app.models import Company, FeatureUsageEvent
from tests.test_collection import make_project


def login_admin(client, users, db):
    users[0].is_admin = True
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": users[0].email, "password": "test-only-long-password"},
    )
    assert response.status_code == 200
    return client


def test_usage_report_is_admin_only(auth):
    assert auth.get("/api/admin/usage-report").status_code == 404


def test_usage_report_counts_3000_companies_with_bounded_queries(client, users, db):
    admin = login_admin(client, users, db)
    project = make_project(admin)
    project_id = UUID(project["id"])
    db.add_all(
        Company(
            project_id=project_id,
            company_name=f"合成企業{index}",
            source="serper",
            website_url=f"https://synthetic-{index}.example.test",
        )
        for index in range(3000)
    )
    db.add(FeatureUsageEvent(event_type="collection_condition_proposal"))
    db.commit()

    statements = []

    def count_query(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    bind = db.get_bind()
    event.listen(bind, "before_cursor_execute", count_query)
    try:
        response = admin.get("/api/admin/usage-report")
    finally:
        event.remove(bind, "before_cursor_execute", count_query)

    assert response.status_code == 200
    report = response.json()
    assert report["window_days"] == 90
    assert report["companies_by_source"] == [{"source": "serper", "count": 3000}]
    assert report["historical_proposal_calls"] is None
    assert any(
        row["event_type"] == "collection_condition_proposal" and row["count"] == 1
        for row in report["feature_usage_events"]
    )
    assert report["coverage"]["processing_usage_partial"] is True
    assert len(statements) <= 30

