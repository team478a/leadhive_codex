from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from app import worker
from app.config import settings
from app.models import (
    Company,
    FormDmReadinessResult,
    FormProfile,
    OperationJob,
    Project,
    TargetProfile,
)
from app.services import sending_window
from browser_worker.jobs import (
    _finish,
    _finish_analysis_batch,
    claim_browser_job,
    recover_stale_browser_jobs,
)


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


def test_browser_analysis_targeting_excludes_blocked_and_captcha_and_prioritizes_readiness(
    db, users, monkeypatch
):
    from app.services import browser_form_analysis

    project = _project(db, users[0])

    def add_candidate(name, compatibility, captcha="CAPTCHA_NONE"):
        host = f"{name.lower()}.example"
        company = Company(
            project_id=project.id,
            company_name=name,
            domain=host,
            website_url=f"https://{host}/",
            contact_url=f"https://{host}/contact",
            source="csv",
        )
        db.add(company)
        db.flush()
        profile = FormProfile(
            company_id=company.id,
            form_url=company.contact_url,
            form_index=0,
            is_primary=True,
            form_found=True,
            sales_contact_status="ALLOWED",
            compatibility_reason_code=compatibility,
            captcha_type=captcha,
            analysis_source="static",
        )
        db.add(profile)
        db.flush()
        return company, profile

    unranked = add_candidate("A-unranked", "CONTACT_FORM_7")
    priority = add_candidate("Z-priority", "NO_NATIVE_SUBMIT")
    blocked = add_candidate("B-blocked", "CONTACT_FORM_7")
    visible_captcha = add_candidate("C-visible-captcha", "CONTACT_FORM_7", "CAPTCHA_RECAPTCHA_V2")
    invisible_captcha = add_candidate(
        "C-invisible-captcha", "CONTACT_FORM_7", "CAPTCHA_RECAPTCHA_V3"
    )
    legacy_captcha = add_candidate("C-legacy-captcha", "CONTACT_FORM_7", "CAPTCHA_RECAPTCHA")
    custom_submit = add_candidate("D-custom-submit", "CUSTOM_SUBMIT_HANDLER")
    analyzed = add_candidate("E-analyzed", "CONTACT_FORM_7")
    analyzed[1].analysis_source = "browser"
    blocked_candidates = []
    for index, reason in enumerate(
        (
            "CONTACT_PROHIBITED",
            "NON_COMPANY_SUSPECTED",
            "ALREADY_SENT_OR_UNKNOWN",
            "RESERVATION_FORM",
            "CAPTCHA_VISIBLE",
            "CAPTCHA_INVISIBLE",
            "CAPTCHA_LEGACY",
        )
    ):
        blocked_candidates.append((add_candidate(f"F-blocked-{index}", "CONTACT_FORM_7"), reason))
    snapshot = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="completed",
        finished_at=datetime.now(timezone.utc),
        payload={},
    )
    db.add(snapshot)
    db.flush()
    for company, profile, reason, secondary in (
        (*unranked, "OTHER_UNSUPPORTED", []),
        (*priority, "NO_NATIVE_SUBMIT", []),
        (*blocked, "CF7", ["NON_COMPANY_SUSPECTED"]),
        (*visible_captcha, "CAPTCHA_VISIBLE", []),
        (*invisible_captcha, "CAPTCHA_INVISIBLE", []),
        (*legacy_captcha, "CAPTCHA_LEGACY", []),
        *[(*candidate, reason, []) for candidate, reason in blocked_candidates],
    ):
        db.add(
            FormDmReadinessResult(
                job_id=snapshot.id,
                company_id=company.id,
                profile_id=profile.id,
                primary_reason=reason,
                secondary_reasons=secondary,
                review_queue_eligible=False,
            )
        )
    db.commit()
    monkeypatch.setattr(
        browser_form_analysis,
        "_target_url",
        lambda company, profile: (profile.form_url, company.domain),
    )

    targets = browser_form_analysis.select_browser_analysis_targets(db, project.id)

    assert [target.company_id for target in targets] == [
        priority[0].id,
        unranked[0].id,
        custom_submit[0].id,
    ]
    assert browser_form_analysis.count_browser_analysis_targets(db, project.id) == 3
    assert browser_form_analysis.SUPPORTED_FORM_REASONS == (
        browser_form_analysis.BROWSER_DELIVERY_COMPATIBILITY
    )
    from app.services.browser_form_preparation import ALLOWED_COMPATIBILITY

    assert ALLOWED_COMPATIBILITY - {""} == browser_form_analysis.SUPPORTED_FORM_REASONS


def test_completed_rendered_analysis_queues_one_readiness_job(db, users, monkeypatch):
    monkeypatch.setattr("browser_worker.jobs.SessionLocal", lambda: nullcontext(db))
    project = _project(db, users[0])
    worker_id = uuid4()
    analysis = OperationJob(
        project_id=project.id,
        operation_type="browser_form_analysis",
        status="running",
        worker_id=worker_id,
        payload={"mode": "rendered_analysis", "targets": [{}]},
        total_count=1,
        processed_count=1,
        success_count=1,
    )
    db.add(analysis)
    db.commit()

    _finish_analysis_batch(analysis.id, worker_id)

    db.expire_all()
    assert db.get(OperationJob, analysis.id).status == "completed"
    readiness = db.scalar(
        select(OperationJob).where(
            OperationJob.project_id == project.id,
            OperationJob.operation_type == "form_dm_readiness",
        )
    )
    assert readiness is not None
    assert readiness.payload == {
        "trigger": "browser_form_analysis",
        "source_job_id": str(analysis.id),
    }


def test_rendered_analysis_does_not_duplicate_active_readiness(db, users, monkeypatch):
    monkeypatch.setattr("browser_worker.jobs.SessionLocal", lambda: nullcontext(db))
    project = _project(db, users[0])
    active = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="running",
        payload={},
    )
    worker_id = uuid4()
    analysis = OperationJob(
        project_id=project.id,
        operation_type="browser_form_analysis",
        status="running",
        worker_id=worker_id,
        payload={"mode": "rendered_analysis", "targets": [{}]},
        total_count=1,
        processed_count=1,
        success_count=1,
    )
    db.add_all([active, analysis])
    db.commit()

    _finish_analysis_batch(analysis.id, worker_id)

    db.expire_all()
    assert db.get(OperationJob, analysis.id).status == "completed"
    readiness_jobs = db.scalars(
        select(OperationJob).where(
            OperationJob.project_id == project.id,
            OperationJob.operation_type == "form_dm_readiness",
        )
    ).all()
    assert [job.id for job in readiness_jobs] == [active.id]


def test_cancelled_rendered_analysis_does_not_queue_readiness(db, users, monkeypatch):
    monkeypatch.setattr("browser_worker.jobs.SessionLocal", lambda: nullcontext(db))
    project = _project(db, users[0])
    worker_id = uuid4()
    analysis = OperationJob(
        project_id=project.id,
        operation_type="browser_form_analysis",
        status="running",
        worker_id=worker_id,
        cancel_requested=True,
        payload={"mode": "rendered_analysis", "targets": [{}]},
        total_count=1,
    )
    db.add(analysis)
    db.commit()

    _finish_analysis_batch(analysis.id, worker_id)

    db.expire_all()
    assert db.get(OperationJob, analysis.id).status == "cancelled"
    assert (
        db.scalar(
            select(OperationJob.id).where(
                OperationJob.project_id == project.id,
                OperationJob.operation_type == "form_dm_readiness",
            )
        )
        is None
    )


def test_failed_browser_analysis_does_not_queue_readiness(db, users, monkeypatch):
    monkeypatch.setattr("browser_worker.jobs.SessionLocal", lambda: nullcontext(db))
    project = _project(db, users[0])
    worker_id = uuid4()
    analysis = OperationJob(
        project_id=project.id,
        operation_type="browser_form_analysis",
        status="running",
        worker_id=worker_id,
        payload={"mode": "rendered_analysis", "targets": [{}]},
        total_count=1,
    )
    db.add(analysis)
    db.commit()

    _finish(analysis.id, worker_id, error="synthetic failure")

    db.expire_all()
    assert db.get(OperationJob, analysis.id).status == "failed"
    assert (
        db.scalar(
            select(OperationJob.id).where(
                OperationJob.project_id == project.id,
                OperationJob.operation_type == "form_dm_readiness",
            )
        )
        is None
    )
