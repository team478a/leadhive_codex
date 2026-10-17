from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import event, func, select

from app.database import engine
from app.models import (
    ApprovalRequest,
    ApprovedEmailBatch,
    ApprovedEmailReservation,
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
from tests import test_approval_foundation as approval_foundation
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source
from tests.test_form_approval_preparation import prepare as prepare_form_approval


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


def test_bulk_template_drafts_server_selects_email_companies_without_email_drafts(auth, db):
    project = make_project(auth)
    eligible, no_email, prohibited, suppressed, drafted, form_draft = add_companies(
        db, UUID(project["id"]), 6
    )
    no_email.email = ""
    prohibited.do_not_contact = True
    db.add(
        SuppressionEntry(
            project_id=UUID(project["id"]),
            domain=suppressed.domain,
            email="",
            phone="",
            reason="suppressed",
        )
    )
    db.add_all(
        [
            OutreachDraft(company_id=drafted.id, channel="email", subject="既存", body="既存"),
            OutreachDraft(company_id=form_draft.id, channel="form", subject="", body="既存"),
        ]
    )
    db.commit()
    template = make_template(auth, project["id"])

    response = auth.post(
        f"/api/projects/{project['id']}/outreach-drafts/bulk-from-template",
        json={
            "template_id": template["id"],
            "channel": "email",
            "readiness_reason": "NO_EMAIL_DRAFT",
        },
    )

    assert response.status_code == 202, response.text
    job = db.get(OperationJob, UUID(response.json()["id"]))
    assert job.payload["targets"] == [
        {"company_id": str(eligible.id), "profile_id": None},
        {"company_id": str(form_draft.id), "profile_id": None},
    ]


def test_send_flow_summary_counts_only_unexpired_unreserved_approvals(
    auth, db, workspace, form_source, monkeypatch
):
    project, company = workspace
    company.email = "recipient@example.com"
    db.commit()
    unreserved_item = approval_foundation.create(auth, workspace)
    reserved_item = approval_foundation.create(auth, workspace)
    for item in (unreserved_item, reserved_item):
        assert (
            approval_foundation.approve(
                auth, item, approval_foundation.challenge(auth, item)
            ).status_code
            == 200
        )

    approved_request = db.get(ApprovalRequest, UUID(reserved_item["id"]))
    now = datetime.now(timezone.utc)
    batch = ApprovedEmailBatch(
        project_id=project.id,
        created_by_user_id=project.user_id,
        idempotency_key=uuid4(),
        request_hash="a" * 64,
        name="reserved",
    )
    draft = OutreachDraft(company_id=company.id, channel="email", subject="承認済み", body="本文")
    db.add_all([batch, draft])
    db.flush()
    delivery = EmailDelivery(
        draft_id=draft.id,
        company_id=company.id,
        recipient_email="recipient@example.com",
        subject="承認済み",
        body="本文",
        scheduled_for=now,
        confirmed_at=now,
    )
    db.add(delivery)
    db.flush()
    db.add(
        ApprovedEmailReservation(
            batch_id=batch.id,
            approval_id=approved_request.id,
            delivery_id=delivery.id,
            envelope={},
            envelope_hash="b" * 64,
            sender_email="sender@example.com",
            recipient_email="recipient@example.com",
        )
    )

    form_item = prepare_form_approval(auth, form_source)
    assert (
        approval_foundation.approve(
            auth, form_item, approval_foundation.challenge(auth, form_item)
        ).status_code
        == 200
    )
    form_project, form_company, form_draft, form_profile, *_ = form_source
    form_request = db.get(ApprovalRequest, UUID(form_item["id"]))
    db.add(
        ApprovedFormDispatch(
            approval_id=form_request.id,
            project_id=form_project.id,
            company_id=form_company.id,
            draft_id=form_draft.id,
            created_by_user_id=form_project.user_id,
            idempotency_key=uuid4(),
            request_hash="c" * 64,
            payload_snapshot={"delivery_method": "direct"},
            payload_hash="d" * 64,
            form_url=form_profile.form_url,
        )
    )
    db.commit()

    response = auth.get(f"/api/projects/{project.id}/send-flow-summary")

    assert response.status_code == 200, response.text
    assert response.json()["approval_counts"]["approved_unsent"] == {
        "email": 1,
        "form": 0,
    }

    class FutureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            future = now + timedelta(days=3)
            return future.astimezone(tz) if tz else future.replace(tzinfo=None)

    from app import send_flow_routes

    monkeypatch.setattr(send_flow_routes, "datetime", FutureDateTime)
    expired_response = auth.get(f"/api/projects/{project.id}/send-flow-summary")

    assert expired_response.status_code == 200, expired_response.text
    assert expired_response.json()["approval_counts"]["approved_unsent"] == {
        "email": 0,
        "form": 0,
    }


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
