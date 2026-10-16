from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import event, func, select

from app.database import engine
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    Company,
    EmailDelivery,
    FormDelivery,
    FormDmReadinessResult,
    OperationJob,
    OutreachDraft,
    SuppressionEntry,
)
from app.services import bulk_template_drafts
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def make_project(auth):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    response = auth.post(
        "/api/projects",
        json={
            "project_name": "送信フロー",
            "target_profile_id": profile_id,
            "sales_objective": "サービスの案内",
            "region": "全国",
            "status": "active",
        },
    )
    assert response.status_code == 201
    return response.json()


def add_companies(db, project_id, count, *, email=True):
    companies = [
        Company(
            project_id=project_id,
            company_name=f"テスト企業{index:04}",
            domain=f"bulk-{index}.example.test",
            website_url=f"https://bulk-{index}.example.test",
            email=f"contact@bulk-{index}.example.test" if email else "",
            source="url",
        )
        for index in range(count)
    ]
    db.add_all(companies)
    db.flush()
    return companies


def make_template(auth, project_id, channel="email", body=None):
    response = auth.post(
        f"/api/projects/{project_id}/outreach-templates",
        json={
            "name": "一括作成用",
            "channel": channel,
            "subject": "{{会社名}}へのご案内",
            "body": body
            or (
                "{{会社名}} {{送信者名}} {{送信者会社名}} {{送信者メール}} {{送信者電話}}。"
                "今後のご案内が不要な場合はご返信ください。"
            ),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def run_queued_job(db, job_id):
    job = db.get(OperationJob, UUID(job_id))
    job.status = "running"
    job.worker_id = uuid4()
    db.commit()
    bulk_template_drafts.run_bulk_template_drafts(db, job, job.worker_id, lambda *_: False)
    return db.get(OperationJob, UUID(job_id))


def test_bulk_template_drafts_caps_at_500_and_commits_in_chunks(auth, db, monkeypatch):
    project = make_project(auth)
    companies = add_companies(db, UUID(project["id"]), 500)
    template = make_template(auth, project["id"])
    monkeypatch.setattr(
        bulk_template_drafts,
        "evaluate_contact_permission",
        lambda *_args: SimpleNamespace(
            status="ALLOWED", reason_code="allowed", message="送信できます。"
        ),
    )
    response = auth.post(
        f"/api/projects/{project['id']}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "email",
            "company_ids": [str(company.id) for company in companies],
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["total_count"] == 500

    job = run_queued_job(db, response.json()["id"])
    assert job.processed_count == 500
    assert job.success_count == 500
    assert (
        db.scalar(
            select(func.count())
            .select_from(OutreachDraft)
            .join(Company)
            .where(Company.project_id == UUID(project["id"]))
        )
        == 500
    )


def test_bulk_template_drafts_can_select_saved_no_form_draft_readiness(auth, db, form_source):
    project, company, draft, profile, _sender, _fields = form_source
    project_id = project.id
    company_id = company.id
    profile_id = profile.id
    db.delete(draft)
    snapshot = OperationJob(
        project_id=project_id,
        operation_type="form_dm_readiness",
        status="completed",
        finished_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.flush()
    db.add(
        FormDmReadinessResult(
            job_id=snapshot.id,
            company_id=company_id,
            profile_id=profile_id,
            primary_reason="NO_FORM_DRAFT",
            secondary_reasons=[],
            review_queue_eligible=False,
            classified_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    template = make_template(auth, str(project_id), channel="form")
    response = auth.post(
        f"/api/projects/{project_id}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "form",
            "readiness_reason": "NO_FORM_DRAFT",
        },
    )
    assert response.status_code == 202, response.text
    job = db.get(OperationJob, UUID(response.json()["id"]))
    assert job.payload["targets"] == [
        {"company_id": str(company_id), "profile_id": str(profile_id)}
    ]


def test_bulk_template_drafts_skip_existing_and_exclude_contact_prohibitions(auth, db):
    project = make_project(auth)
    permitted, prohibited, suppressed, existing = add_companies(db, UUID(project["id"]), 4)
    permitted_id, prohibited_id, suppressed_id, existing_id = (
        permitted.id,
        prohibited.id,
        suppressed.id,
        existing.id,
    )
    prohibited.do_not_contact = True
    db.add(
        SuppressionEntry(
            project_id=UUID(project["id"]),
            domain=suppressed.domain,
            email="",
            phone="",
            reason="manual suppression",
        )
    )
    db.add(
        OutreachDraft(
            company_id=existing.id,
            channel="email",
            subject="手動下書き",
            body="上書きしてはいけない本文",
        )
    )
    db.commit()
    template = make_template(auth, project["id"])
    response = auth.post(
        f"/api/projects/{project['id']}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "email",
            "company_ids": [
                str(company_id)
                for company_id in (permitted_id, prohibited_id, suppressed_id, existing_id)
            ],
        },
    )
    assert response.status_code == 202, response.text
    job = run_queued_job(db, response.json()["id"])
    result = job.payload["bulk_template_results"]
    assert result["created"] == [str(permitted_id)], {
        "created": result["created"],
        "skipped_existing": result["skipped_existing"],
        "excluded": [(item["company_id"], item["reason_code"]) for item in result["excluded"]],
        "processed_count": job.processed_count,
        "total_count": job.total_count,
    }
    assert result["skipped_existing"] == [str(existing_id)]
    assert {item["reason_code"] for item in result["excluded"]} == {
        "company_do_not_contact",
        "suppression_domain",
    }

    draft = db.scalar(select(OutreachDraft).where(OutreachDraft.company_id == permitted_id))
    assert "テスト企業0000" in draft.subject
    assert "今後のご案内が不要な場合はご返信ください" in draft.body
    preserved = db.scalar(select(OutreachDraft).where(OutreachDraft.company_id == existing_id))
    assert preserved.body == "上書きしてはいけない本文"
    assert db.scalar(select(func.count()).select_from(ApprovalRequest)) == 0
    assert db.scalar(select(func.count()).select_from(ApprovedFormDispatch)) == 0
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == 0

    job.status = "completed"
    job.worker_id = None
    db.commit()
    repeated = auth.post(
        f"/api/projects/{project['id']}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "email",
            "company_ids": [str(permitted_id)],
        },
    )
    assert repeated.status_code == 202
    repeated_job = run_queued_job(db, repeated.json()["id"])
    assert repeated_job.payload["bulk_template_results"]["created"] == []
    assert repeated_job.payload["bulk_template_results"]["skipped_existing"] == [str(permitted_id)]


def test_send_flow_summary_uses_bounded_queries_for_large_project(auth, db):
    project = make_project(auth)
    add_companies(db, UUID(project["id"]), 3000)
    db.add(
        OperationJob(
            project_id=UUID(project["id"]),
            operation_type="form_dm_readiness",
            status="completed",
            finished_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    statements = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        response = auth.get(f"/api/projects/{project['id']}/send-flow-summary")
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200, response.text
    assert response.json()["target_company_count"] == 0
    assert len(statements) <= 12
    assert response.json()["draft_counts"] == {"email": 0, "form": 0}
