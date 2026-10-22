import csv
import io
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select

from app.models import Company, FormAnalysisLog, FormProfile, Project, ProjectMember
from app.services.pipeline_stages import STAGES, classify_pipeline_stage, collect_pipeline_stages
from tests.conftest import PASSWORD
from tests.test_approval_foundation import workspace as workspace


def company(**overrides):
    values = {
        "id": uuid4(),
        "project_id": uuid4(),
        "company_name": "株式会社テスト",
        "record_type": "company",
        "source": "url",
        "website_url": "https://example.com",
        "analysis_status": "completed",
        "do_not_contact": False,
    }
    values.update(overrides)
    return Company(**values)


def profile(**overrides):
    values = {
        "company_id": uuid4(),
        "form_url": "https://example.com/contact",
        "form_status": "READY",
        "form_found": True,
    }
    values.update(overrides)
    return FormProfile(**values)


READY = SimpleNamespace(primary_reason="READY")
APPROVED = SimpleNamespace(status="APPROVED")
SUBMITTED = SimpleNamespace(status="submitted")
FOUND = {"profile": profile(), "form_found_count": 1}


@pytest.mark.parametrize(
    ("expected", "company_overrides", "profile_data", "readiness", "approval", "delivery"),
    [
        ("NOT_COMPANY_RECORD", {"record_type": "location"}, FOUND, READY, APPROVED, SUBMITTED),
        (
            "DUPLICATE_OR_EXCLUDED",
            {"analysis_status": "excluded"},
            FOUND,
            READY,
            APPROVED,
            SUBMITTED,
        ),
        ("DO_NOT_CONTACT", {"do_not_contact": True}, FOUND, READY, APPROVED, SUBMITTED),
        ("NO_WEBSITE", {"website_url": ""}, FOUND, READY, APPROVED, SUBMITTED),
        ("SITE_NOT_ANALYZED", {"analysis_status": "running"}, FOUND, READY, APPROVED, SUBMITTED),
        (
            "SITE_ANALYSIS_FAILED",
            {"analysis_status": "failed"},
            FOUND,
            READY,
            APPROVED,
            SUBMITTED,
        ),
        ("NO_FORM_PROFILE", {}, None, READY, APPROVED, SUBMITTED),
        (
            "FORM_ANALYSIS_INCOMPLETE",
            {},
            {"profile": profile(form_status="ERROR"), "form_found_count": 1},
            READY,
            APPROVED,
            SUBMITTED,
        ),
        (
            "FORM_FOUND_ON_NON_PRIMARY",
            {},
            {"profile": profile(form_found=False), "form_found_count": 1},
            READY,
            APPROVED,
            SUBMITTED,
        ),
        (
            "FORM_NOT_FOUND",
            {},
            {"profile": profile(form_found=False), "form_found_count": 0},
            READY,
            APPROVED,
            SUBMITTED,
        ),
        ("READINESS_NOT_CALCULATED", {}, FOUND, None, APPROVED, SUBMITTED),
        (
            "BLOCKED_AT_READINESS",
            {},
            FOUND,
            SimpleNamespace(primary_reason="CF7"),
            APPROVED,
            SUBMITTED,
        ),
        ("READY_NOT_REQUESTED", {}, FOUND, READY, None, None),
        ("AWAITING_APPROVAL", {}, FOUND, READY, SimpleNamespace(status="PENDING"), None),
        ("APPROVAL_CLOSED", {}, FOUND, READY, SimpleNamespace(status="REJECTED"), None),
        ("APPROVED_NOT_SENT", {}, FOUND, READY, APPROVED, None),
        ("SENT", {}, FOUND, READY, APPROVED, SUBMITTED),
        (
            "SEND_FAILED_OR_UNKNOWN",
            {},
            FOUND,
            READY,
            APPROVED,
            SimpleNamespace(status="unknown"),
        ),
    ],
)
def test_all_pipeline_stages(
    expected, company_overrides, profile_data, readiness, approval, delivery
):
    result = classify_pipeline_stage(
        company(**company_overrides), profile_data, readiness, approval, delivery
    )
    assert result.stage == expected
    assert [item.order for item in STAGES] == list(range(1, 19))


def test_stage_precedence_puts_do_not_contact_before_sent():
    result = classify_pipeline_stage(
        company(do_not_contact=True),
        {"profile": profile(), "form_found_count": 1},
        READY,
        APPROVED,
        SimpleNamespace(status="submitted"),
    )
    assert result.stage == "DO_NOT_CONTACT"


def test_pipeline_summary_and_csv_cover_each_company_once(auth, workspace, db):
    project, first = workspace
    first.company_name = "=数式会社"
    first.website_url = ""
    first.analysis_status = "pending"
    first.phone = "090-0000-0000"
    first.email = "secret@example.com"
    second = company(
        project_id=project.id,
        company_name="フォーム未解析会社",
        website_url="https://second.example",
        domain="second.example",
        analysis_status="completed",
    )
    other_project = Project(
        user_id=project.user_id,
        project_name="別案件",
        target_profile_id=project.target_profile_id,
        sales_objective="案件分離の確認",
        region="全国",
    )
    db.add(other_project)
    db.flush()
    outsider = company(
        project_id=other_project.id,
        company_name="別案件",
        website_url="",
        analysis_status="pending",
    )
    db.add_all([second, outsider])
    db.commit()

    summary = auth.get(f"/api/projects/{project.id}/pipeline-stages/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total_companies"] == 2
    assert sum(row["count"] for row in body["stages"]) == 2
    assert len(body["stages"]) == 18
    assert body["stages"][3]["count"] == 1
    assert body["stages"][6]["count"] == 1

    exported = auth.get(f"/api/projects/{project.id}/pipeline-stages.csv")
    assert exported.status_code == 200, exported.text
    assert exported.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(rows) == 2
    assert {row["company_id"] for row in rows} == {str(first.id), str(second.id)}
    assert Counter(row["stage"] for row in rows) == {
        row["stage"]: row["count"] for row in body["stages"] if row["count"]
    }
    formula_row = next(row for row in rows if row["company_id"] == str(first.id))
    assert formula_row["company_name"] == "'=数式会社"
    assert "email" not in rows[0]
    assert "phone" not in rows[0]
    assert "notes" not in rows[0]
    assert "ai_summary" not in rows[0]


def test_pipeline_uses_shared_primary_profile_order_and_finds_non_primary(workspace, db):
    project, company_row = workspace
    company_row.analysis_status = "completed"
    primary = profile(
        company_id=company_row.id,
        form_url="https://approval.example/contact",
        form_status="REVIEW_REQUIRED",
        form_found=False,
        is_primary=True,
    )
    secondary = profile(
        company_id=company_row.id,
        form_url="https://approval.example/inquiry",
        form_status="READY",
        form_found=True,
        is_primary=False,
    )
    db.add_all([secondary, primary])
    db.commit()

    data = collect_pipeline_stages(db, project.id)

    assert data["rows"][0]["stage"].stage == "FORM_FOUND_ON_NON_PRIMARY"
    assert data["rows"][0]["profile"].id == primary.id
    assert data["rows"][0]["form_found_count"] == 1


def test_form_not_found_uses_existing_missing_diagnosis(workspace, db):
    project, company_row = workspace
    company_row.analysis_status = "completed"
    missing_profile = profile(
        company_id=company_row.id,
        form_url="https://approval.example/contact",
        form_status="REVIEW_REQUIRED",
        form_found=False,
        is_primary=True,
        analysis_version="2.5",
    )
    db.add(missing_profile)
    db.flush()
    db.add_all(
        [
            FormAnalysisLog(
                company_id=company_row.id,
                form_profile_id=missing_profile.id,
                event_type="contact_page_found",
                details={
                    "url": "https://approval.example/contact",
                    "discovery_method": "LINK",
                },
            ),
            FormAnalysisLog(
                company_id=company_row.id,
                form_profile_id=missing_profile.id,
                event_type="analysis_completed",
                details={"finding": "DOM_CONTACT_FORM_NOT_FOUND"},
            ),
        ]
    )
    db.commit()

    data = collect_pipeline_stages(db, project.id)

    assert data["rows"][0]["stage"].stage == "FORM_NOT_FOUND"
    assert data["rows"][0]["missing_form"]["primary_reason"] == "PAGE_FOUND_NO_FORM"
    assert data["rows"][0]["missing_form"]["last_reached_url"] == "https://approval.example/contact"


def test_pipeline_stage_access_allows_viewer_only(auth, workspace, db, users):
    project, _company = workspace
    auth.post("/api/auth/logout")
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert auth.get(f"/api/projects/{project.id}/pipeline-stages/summary").status_code == 404
    db.add(ProjectMember(project_id=project.id, user_id=users[1].id, role="viewer"))
    db.commit()
    assert auth.get(f"/api/projects/{project.id}/pipeline-stages/summary").status_code == 200
    assert auth.get(f"/api/projects/{project.id}/pipeline-stages.csv").status_code == 200


def test_pipeline_stage_reads_do_not_create_records(auth, workspace, db):
    from app.models import ApprovalRequest, FormAnalysisLog, FormDelivery, OperationJob

    project, _company = workspace
    models = (OperationJob, ApprovalRequest, FormDelivery, FormAnalysisLog)
    before = {model: db.scalar(select(func.count()).select_from(model)) for model in models}
    assert auth.get(f"/api/projects/{project.id}/pipeline-stages/summary").status_code == 200
    assert auth.get(f"/api/projects/{project.id}/pipeline-stages.csv").status_code == 200
    db.expire_all()
    after = {model: db.scalar(select(func.count()).select_from(model)) for model in models}
    assert after == before


def test_pipeline_stage_query_count_is_bounded_for_6000_companies(workspace, db):
    project, company_row = workspace
    db.delete(company_row)
    db.flush()
    db.execute(
        insert(Company),
        [
            {
                "id": uuid4(),
                "project_id": project.id,
                "company_name": f"会社{index:04d}",
                "record_type": "company",
                "source": "url",
                "website_url": None,
                "analysis_status": "pending",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            for index in range(6000)
        ],
    )
    db.flush()
    statements = []

    def count_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count_statement)
    try:
        data = collect_pipeline_stages(db, project.id)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count_statement)
    assert data["total_companies"] == 6000
    assert len(statements) <= 7
