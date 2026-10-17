from datetime import datetime, timedelta, timezone
from uuid import UUID

from app import worker
from app.config import settings
from app.models import Company, FormProfile, OperationJob, Project, TargetProfile
from app.services import sending_window
from browser_worker.jobs import claim_browser_job, recover_stale_browser_jobs


def _project(db, user):
    profile = TargetProfile(user_id=user.id, profile_name="Browser synthetic fixture")
    db.add(profile)
    db.flush()
    project = Project(
        user_id=user.id,
        target_profile_id=profile.id,
        project_name="Browser synthetic fixture",
        sales_objective="Offline testing only",
        region="全国",
    )
    db.add(project)
    db.flush()
    return project


def test_api_queues_only_synthetic_fixtures_and_deduplicates(auth, db, users, monkeypatch):
    project = _project(db, users[0])
    path = f"/api/projects/{project.id}/browser-form-analysis"
    response = auth.post(
        path,
        json={"fixture": "normal", "fields": {"input[name='name']": "Synthetic"}},
    )
    assert response.status_code == 202
    queued = response.json()
    assert queued["operation_type"] == "browser_form_analysis"
    stored = db.get(OperationJob, UUID(queued["id"]))
    assert stored.payload["fixture"] == "normal"
    assert "url" not in stored.payload

    assert auth.post(path, json={"fixture": "normal", "fields": {}}).status_code == 409
    real_url = auth.post(path, json={"fixture": "normal", "url": "https://example.com"})
    assert real_url.status_code == 422
    assert auth.post(path, json={"fixture": "https://example.com"}).status_code == 422

    monkeypatch.setattr(sending_window, "allowed", lambda _db: True)
    assert worker.claim_job(db) is None
    assert db.get(OperationJob, UUID(queued["id"])).status == "queued"


def test_browser_job_claim_cancel_and_stale_recovery_use_operation_lease(auth, db, users):
    project = _project(db, users[0])
    response = auth.post(
        f"/api/projects/{project.id}/browser-form-analysis",
        json={"fixture": "normal", "fields": {}},
    )
    job_id = response.json()["id"]

    job = claim_browser_job(db)
    assert job is not None and str(job.id) == job_id
    assert job.status == "running"
    assert job.worker_id is not None
    assert job.lease_expires_at is not None
    assert job.payload["executed_by_commit"]
    assert job.payload["executed_by_host"]

    cancelled = auth.post(f"/api/operations/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancel_requested"] is True
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    assert recover_stale_browser_jobs(db) == (0, 0)
    assert db.get(OperationJob, job.id).status == "cancelled"


def test_real_site_analysis_is_off_by_default_and_server_caps_each_job_at_100(
    auth, db, users, monkeypatch
):
    from app.services import browser_form_analysis

    project = _project(db, users[0])
    companies = []
    for index in range(101):
        host = f"company-{index}.example"
        company = Company(
            project_id=project.id,
            company_name=f"解析対象{index}",
            domain=host,
            website_url=f"https://{host}/",
            contact_url=f"https://{host}/contact",
            source="csv",
        )
        db.add(company)
        db.flush()
        db.add(
            FormProfile(
                company_id=company.id,
                form_url=company.contact_url,
                form_index=0,
                is_primary=True,
                form_found=True,
                sales_contact_status="ALLOWED",
                compatibility_reason_code="CONTACT_FORM_7",
                analysis_source="static",
            )
        )
        companies.append(company)
    db.commit()

    path = f"/api/projects/{project.id}/browser-form-analysis/recalculate"
    monkeypatch.setattr(settings, "browser_form_analysis_enabled", False)
    disabled = auth.post(path)
    assert disabled.status_code == 409
    assert "田中さんの承認後" in disabled.json()["detail"]

    monkeypatch.setattr(settings, "browser_form_analysis_enabled", True)
    monkeypatch.setattr(
        browser_form_analysis,
        "_target_url",
        lambda company, profile: (profile.form_url, company.domain),
    )
    monkeypatch.setattr(
        browser_form_analysis,
        "validate_target",
        lambda url: url.split("//", 1)[1].split("/", 1)[0],
    )
    queued = auth.post(path)
    assert queued.status_code == 202
    job = db.get(OperationJob, UUID(queued.json()["id"]))
    assert job.total_count == 100
    assert job.payload["mode"] == "rendered_analysis"
    assert len(job.payload["targets"]) == 100
    assert all(
        "fixture" not in target and "fields" not in target for target in job.payload["targets"]
    )
