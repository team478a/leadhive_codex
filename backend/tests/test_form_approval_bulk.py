from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models import ApprovalRequest, Company, FormDmReadinessResult, OperationJob, User
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source


def test_bulk_request_queues_ready_companies_and_worker_is_idempotent(auth, form_source, db):
    project, company = form_source[:2]
    response = auth.post(
        f"/api/projects/{project.id}/form-approval-requests/bulk",
        json={"company_ids": [str(company.id)]},
    )

    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["operation_type"] == "form_approval_batch"
    assert queued["total_count"] == 1

    worker_id = uuid4()
    job = db.get(OperationJob, UUID(queued["id"]))
    job.status = "running"
    job.worker_id = worker_id
    db.commit()

    from app.worker import run_form_approval_batch

    run_form_approval_batch(db, job, worker_id)
    db.refresh(job)
    assert job.processed_count == 1
    assert job.success_count == 1
    assert job.payload["results"][0]["status"] == "created"
    assert (
        db.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.company_id == company.id,
                ApprovalRequest.source_draft_id == form_source[2].id,
            )
        )
        is not None
    )
    job.status = "completed"
    db.commit()

    actor = db.scalar(select(User).order_by(User.id))
    second_worker_id = uuid4()
    repeated = OperationJob(
        project_id=project.id,
        operation_type="form_approval_batch",
        payload={"company_ids": [str(company.id)], "user_id": str(actor.id), "results": []},
        total_count=1,
        status="running",
        worker_id=second_worker_id,
    )
    db.add(repeated)
    db.commit()
    run_form_approval_batch(db, repeated, second_worker_id)
    db.refresh(repeated)
    assert repeated.payload["results"][0]["status"] == "skipped_existing"
    assert (
        db.scalar(
            select(ApprovalRequest.id).where(
                ApprovalRequest.company_id == company.id,
                ApprovalRequest.source_draft_id == form_source[2].id,
            )
        )
        is not None
    )


def test_bulk_request_rejects_more_than_200_company_ids(auth, form_source):
    project = form_source[0]
    response = auth.post(
        f"/api/projects/{project.id}/form-approval-requests/bulk",
        json={"company_ids": [str(uuid4()) for _ in range(201)]},
    )

    assert response.status_code == 422


def test_bulk_all_ready_only_queues_preparation_ready_companies(auth, form_source, db):
    project, company, _, profile = form_source[:4]
    readiness_job = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="completed",
        payload={},
        total_count=1,
        processed_count=1,
        success_count=1,
    )
    db.add(readiness_job)
    db.flush()
    db.add(
        FormDmReadinessResult(
            job_id=readiness_job.id,
            company_id=company.id,
            profile_id=profile.id,
            primary_reason="READY",
            secondary_reasons=[],
            review_queue_eligible=False,
        )
    )
    db.commit()

    response = auth.post(
        f"/api/projects/{project.id}/form-approval-requests/bulk", json={"all_ready": True}
    )

    assert response.status_code == 202, response.text
    assert response.json()["total_count"] == 1
    assert response.json()["operation_type"] == "form_approval_batch"


@pytest.mark.parametrize(
    "captcha_type",
    ["CAPTCHA_RECAPTCHA", "CAPTCHA_RECAPTCHA_V2", "CAPTCHA_RECAPTCHA_V3"],
)
def test_bulk_worker_reports_pr0_reason_for_blocked_company(form_source, db, captcha_type):
    project, company, _, profile = form_source[:4]
    profile.captcha_type = captcha_type
    actor = db.scalar(select(User).order_by(User.id))
    worker_id = uuid4()
    job = OperationJob(
        project_id=project.id,
        operation_type="form_approval_batch",
        payload={"company_ids": [str(company.id)], "user_id": str(actor.id), "results": []},
        total_count=1,
        status="running",
        worker_id=worker_id,
    )
    db.add(job)
    db.commit()

    from app.worker import run_form_approval_batch

    run_form_approval_batch(db, job, worker_id)
    db.refresh(job)

    assert job.payload["results"][0]["status"] == "blocked"
    assert job.payload["results"][0]["reason_code"] == "CAPTCHA"
    assert (
        db.scalar(select(ApprovalRequest.id).where(ApprovalRequest.company_id == company.id))
        is None
    )


def test_bulk_request_accepts_maximum_200_companies(auth, form_source, db):
    project, first_company = form_source[:2]
    companies = [first_company]
    companies.extend(
        Company(
            project_id=project.id,
            company_name=f"一括提案対象{index}",
            source="url",
            website_url=f"https://batch-{index}.example",
            domain=f"batch-{index}.example",
        )
        for index in range(199)
    )
    db.add_all(companies[1:])
    db.commit()

    response = auth.post(
        f"/api/projects/{project.id}/form-approval-requests/bulk",
        json={"company_ids": [str(company.id) for company in companies]},
    )

    assert response.status_code == 202, response.text
    assert response.json()["total_count"] == 200


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"company_ids": [], "all_ready": False},
        {"company_ids": [str(uuid4())], "all_ready": True},
    ],
)
def test_bulk_request_requires_one_scope(auth, form_source, payload):
    project = form_source[0]
    response = auth.post(f"/api/projects/{project.id}/form-approval-requests/bulk", json=payload)

    assert response.status_code == 422
