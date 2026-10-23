from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.form_dm_readiness_routes import READINESS_CSV_FIELDS, readiness_csv_rows
from app.models import Company, FormProfile, FormProfileField, Project, ProjectMember
from tests.test_approval_foundation import workspace as workspace  # noqa: F401
from tests.test_form_approval_preparation import form_source as form_source


def aggregate(auth, db, project):
    project_id = project.id
    response = auth.post(f"/api/projects/{project_id}/form-dm-readiness/recalculate")
    assert response.status_code == 202, response.text
    from app.models import OperationJob
    from app.worker import run_form_dm_readiness

    job = db.get(OperationJob, response.json()["id"])
    job.status, job.worker_id = "running", uuid4()
    db.commit()
    run_form_dm_readiness(db, job, job.worker_id)
    db.refresh(job)
    job.status = "completed"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return project_id


def test_form_dm_readiness_is_read_only_and_exports_csv(auth, form_source, db):
    project, company, _draft, profile, _sender, _fields = form_source
    before = profile.updated_at
    profile_id = profile.id
    company_id, company_name = company.id, company.company_name
    project_id = aggregate(auth, db, project)

    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness")

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["counts"]["READY"] == 1
    assert body["review_queue_eligible"] == 1
    assert body["ready_confirmation_pending"] == 1
    assert body["total"] == 1
    assert body["items"][0]["company_id"] == str(company_id)
    assert body["items"][0]["primary_reason"] == "READY"
    assert body["read_only"] is True
    assert body["external_requests"] == 0
    db.expire_all()
    assert db.get(FormProfile, profile_id).updated_at == before

    exported = auth.get(f"/api/projects/{project_id}/form-dm-readiness?format=csv")
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert exported.content.startswith(b"\xef\xbb\xbf")
    assert "company_name" in exported.text
    assert company_name in exported.text


def test_form_dm_readiness_csv_selects_only_output_columns_and_streams_in_batches():
    fake_db = Mock()
    fake_db.execute.return_value = []
    generator = readiness_csv_rows(
        fake_db,
        snapshot=object(),
        result_filters=[FormProfile.id == uuid4()],
    )
    assert next(generator).startswith("\ufeffcompany_id,company_name,form_url")
    assert list(generator) == []
    statement = fake_db.execute.call_args.args[0]
    assert [column.key for column in statement.selected_columns] == list(READINESS_CSV_FIELDS)
    assert statement.get_execution_options()["yield_per"] == 200


def test_form_dm_readiness_reports_browser_feature_flags(auth, form_source, db, monkeypatch):
    from app.config import settings

    project = form_source[0]
    project_id = aggregate(auth, db, project)
    monkeypatch.setattr(settings, "browser_form_analysis_enabled", True)
    monkeypatch.setattr(settings, "browser_form_dry_run_enabled", False)
    monkeypatch.setattr(settings, "browser_form_delivery_enabled", False)

    body = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()

    assert body["browser_analysis_enabled"] is True
    assert body["browser_dry_run_enabled"] is False
    assert body["browser_delivery_enabled"] is False
    assert body["browser_analysis_counts"]["remaining_targets"] >= 0


def test_form_dm_readiness_recalculate_joins_active_job_after_enqueue_race(
    auth, form_source, db, monkeypatch
):
    from app import form_dm_readiness_routes
    from app.models import OperationJob

    project = form_source[0]
    active_job = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        payload={},
    )

    def simulate_concurrent_enqueue(_db, _job):
        db.add(active_job)
        db.commit()
        return False

    monkeypatch.setattr(form_dm_readiness_routes, "add_operation_job", simulate_concurrent_enqueue)
    response = auth.post(f"/api/projects/{project.id}/form-dm-readiness/recalculate")

    assert response.status_code == 202, response.text
    assert response.json()["id"] == str(active_job.id)
    assert response.json()["status"] == "queued"


def test_form_dm_readiness_retries_a_transient_batch_database_error(
    auth, form_source, db, monkeypatch
):
    from app.models import FormDmReadinessResult, OperationJob
    from app.worker import run_form_dm_readiness

    project = form_source[0]
    job = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="running",
        worker_id=uuid4(),
    )
    db.add(job)
    db.commit()
    real_commit = db.commit
    commit_calls = 0

    def transient_commit():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 2:
            raise OperationalError("synthetic disconnect", {}, ConnectionError())
        real_commit()

    monkeypatch.setattr(db, "commit", transient_commit)
    monkeypatch.setattr("app.worker.time.sleep", lambda _seconds: None)

    run_form_dm_readiness(db, job, job.worker_id)

    assert commit_calls >= 3
    assert db.scalar(select(FormDmReadinessResult).where(FormDmReadinessResult.job_id == job.id))


def test_form_dm_readiness_resumes_from_persisted_results(form_source, db):
    from app.models import FormDmReadinessResult, OperationJob
    from app.worker import run_form_dm_readiness

    project, company, _draft, profile, _sender, _fields = form_source
    worker_id = uuid4()
    job = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="running",
        worker_id=worker_id,
    )
    db.add(job)
    db.flush()
    db.add(
        FormDmReadinessResult(
            job_id=job.id,
            company_id=company.id,
            profile_id=profile.id,
            primary_reason="READY",
            secondary_reasons=[],
            review_queue_eligible=True,
            classified_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    run_form_dm_readiness(db, job, worker_id)

    db.refresh(job)
    assert job.total_count == 1
    assert job.processed_count == 1
    assert job.success_count == 1
    assert (
        len(
            db.scalars(
                select(FormDmReadinessResult).where(FormDmReadinessResult.job_id == job.id)
            ).all()
        )
        == 1
    )


def test_form_dm_readiness_waits_for_bulk_draft_creation(auth, form_source, db):
    from app.models import OperationJob

    project = form_source[0]
    db.add(
        OperationJob(
            project_id=project.id,
            operation_type="bulk_template_drafts",
            status="running",
            worker_id=uuid4(),
        )
    )
    db.commit()

    response = auth.post(f"/api/projects/{project.id}/form-dm-readiness/recalculate")

    assert response.status_code == 409
    assert "一括作成中" in response.json()["detail"]


def test_form_dm_readiness_classifies_prohibition_before_captcha(auth, form_source, db):
    project, company, _draft, profile, _sender, _fields = form_source
    company.do_not_contact = True
    profile.captcha_type = "CAPTCHA_RECAPTCHA"
    project_id = aggregate(auth, db, project)

    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()

    assert result["counts"]["CONTACT_PROHIBITED"] == 1
    assert result["counts"]["CAPTCHA_LEGACY"] == 1
    assert result["items"][0]["primary_reason"] == "CONTACT_PROHIBITED"
    assert result["items"][0]["secondary_reasons"] == ["CAPTCHA_LEGACY"]


@pytest.mark.parametrize(
    ("captcha_type", "expected_reason"),
    [
        ("CAPTCHA_RECAPTCHA_V2", "CAPTCHA_VISIBLE"),
        ("CAPTCHA_HCAPTCHA", "CAPTCHA_VISIBLE"),
        ("CAPTCHA_TURNSTILE", "CAPTCHA_VISIBLE"),
        ("CAPTCHA_IMAGE", "CAPTCHA_VISIBLE"),
        ("CAPTCHA_OTHER", "CAPTCHA_VISIBLE"),
        ("CAPTCHA_RECAPTCHA_V3", "CAPTCHA_INVISIBLE"),
        ("CAPTCHA_CF7_RECAPTCHA", "CAPTCHA_INVISIBLE"),
        ("CAPTCHA_RECAPTCHA", "CAPTCHA_LEGACY"),
    ],
)
def test_form_dm_readiness_classifies_captcha_type(
    auth, form_source, db, captcha_type, expected_reason
):
    project, _company, _draft, profile, _sender, _fields = form_source
    profile.captcha_type = captcha_type
    project_id = aggregate(auth, db, project)

    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()

    assert result["counts"][expected_reason] == 1
    assert expected_reason in [
        result["items"][0]["primary_reason"],
        *result["items"][0]["secondary_reasons"],
    ]


def test_form_dm_readiness_excludes_profiles_without_a_found_form(auth, form_source, db):
    project, _company, _draft, profile, _sender, _fields = form_source
    profile.form_found = False
    project_id = aggregate(auth, db, project)

    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness")

    assert result.status_code == 200, result.text
    assert result.json()["total"] == 0
    assert sum(result.json()["counts"].values()) == 0


@pytest.mark.parametrize(
    ("reason_code", "expected_reason", "has_file"),
    [
        ("NON_POST_METHOD", "NON_POST_METHOD", False),
        ("DUPLICATE_INPUTS", "DUPLICATE_INPUTS", False),
        ("MISSING_NAME_ATTRIBUTE", "MISSING_NAME_ATTRIBUTE", False),
        ("NO_NATIVE_SUBMIT", "NO_NATIVE_SUBMIT", False),
        ("CUSTOM_SUBMIT_HANDLER", "CUSTOM_SUBMIT_HANDLER", False),
        ("NO_INPUT_FIELDS", "NO_INPUT_FIELDS", False),
        ("JAVASCRIPT_CONFIRMATION", "JAVASCRIPT_CONFIRMATION", False),
        ("MULTIPART_OR_FILE", "MULTIPART_ONLY", False),
        ("MULTIPART_OR_FILE", "FILE_ATTACHMENT", True),
        ("PASSWORD_FIELD", "OTHER_UNSUPPORTED", False),
    ],
)
def test_form_dm_readiness_splits_compatibility_reasons(
    auth, form_source, db, reason_code, expected_reason, has_file
):
    project, company, _draft, profile, _sender, _fields = form_source
    company.company_name = ""
    company.domain = "fallback.example"
    profile.compatibility_reason_code = reason_code
    if has_file:
        db.add(
            FormProfileField(
                form_profile_id=profile.id,
                position=99,
                name="attachment",
                field_type="file",
                required=False,
                mapped_key="other",
                confidence=1,
            )
        )
    db.commit()
    project_id = aggregate(auth, db, project)

    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    item = result["items"][0]

    assert expected_reason in [item["primary_reason"], *item["secondary_reasons"]]
    assert item["company_name"] == "fallback.example"


@pytest.mark.parametrize(
    ("company_name", "domain", "expected_evidence"),
    [
        ("2025年度版を調べてみた記事", "news.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("横浜市公式サイト", "city.yokohama.jp", "NON_COMPANY_PUBLIC_DOMAIN"),
        ("自治体ページ", "www.example.lg.jp", "NON_COMPANY_PUBLIC_DOMAIN"),
        ("行政機関案内", "www.example.go.jp", "NON_COMPANY_PUBLIC_DOMAIN"),
        ("学校案内", "school.example.ed.jp", "NON_COMPANY_PUBLIC_DOMAIN"),
        ("大学案内", "university.example.ac.jp", "NON_COMPANY_PUBLIC_DOMAIN"),
        ("2025年版の調査結果", "news.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("»今週のイベント", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("・イベント募集情報", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("【横浜市のお知らせ】", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("新店舗の内覧会がスタート", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("新商品説明会を開催", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("地域の取り組みとは", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("地域イベント募集", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("地域イベント｜横浜市", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        (
            "地域イベントのお知らせと観光案内をまとめた長い記事タイトルです、詳しくは公式サイトをご覧ください。",
            "event.example",
            "NON_COMPANY_ARTICLE_STYLE_NAME",
        ),
        ("2026年度採用募集", "event.example", "NON_COMPANY_ARTICLE_STYLE_NAME"),
        ("", "empty-name.example", "NON_COMPANY_NAME_MISSING"),
        ("-", "dash-name.example", "NON_COMPANY_NAME_MISSING"),
        ("—", "dash-name.example", "NON_COMPANY_NAME_MISSING"),
    ],
)
def test_form_dm_readiness_marks_non_company_signals_and_uses_domain_name(
    auth, form_source, db, company_name, domain, expected_evidence
):
    project, company, _draft, _profile, _sender, _fields = form_source
    company.company_name = company_name
    company.domain = domain
    db.commit()

    project_id = aggregate(auth, db, project)
    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    item = result["items"][0]

    assert item["primary_reason"] == "NON_COMPANY_SUSPECTED"
    assert expected_evidence in item["secondary_reasons"]
    expected_name = company_name.strip() or domain
    if expected_name in {"-", "—"}:
        expected_name = domain
    assert item["company_name"] == expected_name
    assert result["counts"]["NON_COMPANY_SUSPECTED"] == 1


def test_form_dm_readiness_does_not_misclassify_company_name(auth, form_source, db):
    project, company, _draft, _profile, _sender, _fields = form_source
    company.company_name = "株式会社〇〇"
    company.domain = "sample.co.jp"
    company.website_url = "https://sample.co.jp"
    db.commit()

    project_id = aggregate(auth, db, project)
    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    item = result["items"][0]

    assert "NON_COMPANY_SUSPECTED" not in [
        item["primary_reason"],
        *item["secondary_reasons"],
    ]
    assert item["company_name"] == "株式会社〇〇"


def test_location_record_is_marked_as_non_company(auth, form_source, db):
    project, company, _draft, _profile, _sender, _fields = form_source
    company.record_type = "location"
    company.location_key = "a" * 64
    company.company_name = "株式会社〇〇 横浜店"
    company.domain = "shop.example"
    db.commit()

    project_id = aggregate(auth, db, project)
    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    item = result["items"][0]

    assert item["primary_reason"] == "NON_COMPANY_SUSPECTED"
    assert "NON_COMPANY_LOCATION_RECORD" in item["secondary_reasons"]


def test_contact_prohibition_precedes_non_company_suspicion(auth, form_source, db):
    project, company, _draft, _profile, _sender, _fields = form_source
    company_id = company.id
    company.do_not_contact = True
    company.company_name = "【横浜市】2025年度のお知らせ"
    company.domain = "city.yokohama.lg.jp"
    db.commit()

    project_id = aggregate(auth, db, project)
    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    item = result["items"][0]

    assert item["primary_reason"] == "CONTACT_PROHIBITED"
    assert "NON_COMPANY_SUSPECTED" in item["secondary_reasons"]
    assert "NON_COMPANY_PUBLIC_DOMAIN" in item["secondary_reasons"]
    assert result["counts"]["NON_COMPANY_SUSPECTED"] == 1
    filtered = auth.get(f"/api/projects/{project_id}/form-dm-readiness?suspected_only=true").json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["company_id"] == str(company_id)


def test_current_company_review_controls_non_company_suspicion(auth, form_source, db):
    project, company, _draft, _profile, _sender, _fields = form_source
    project_id = project.id
    company_id = company.id
    company.company_name = "2025年度版を調べてみた記事"
    company.domain = "news.example"
    db.commit()
    feedback_path = f"/api/companies/{company.id}/collection-feedback"

    confirmed = auth.post(
        feedback_path,
        json={
            "subject": "company",
            "outcome": "OK",
            "reason": "company_verified",
            "expected_updated_at": company.updated_at.isoformat(),
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    aggregate(auth, db, project)
    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    assert result["counts"]["NON_COMPANY_SUSPECTED"] == 0

    company = db.get(Company, company_id)
    excluded = auth.post(
        feedback_path,
        json={
            "subject": "company",
            "outcome": "NG",
            "reason": "wrong_company",
            "expected_updated_at": company.updated_at.isoformat(),
        },
    )
    assert excluded.status_code == 201, excluded.text
    project = db.get(Project, project_id)
    project_id = aggregate(auth, db, project)
    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    item = result["items"][0]
    assert item["primary_reason"] == "NON_COMPANY_SUSPECTED"
    assert "NON_COMPANY_REVIEW_NG" in item["secondary_reasons"]


def test_form_dm_readiness_viewer_can_read_and_agent_is_not_authorized(
    auth, form_source, users, db
):
    project, _company, *_ = form_source
    original_project_id = project.id
    viewer_id, viewer_email = users[1].id, users[1].email
    owner_email = users[0].email
    project_id = aggregate(auth, db, project)
    db.add(ProjectMember(project_id=original_project_id, user_id=viewer_id, role="viewer"))
    db.commit()
    path = f"/api/projects/{project_id}/form-dm-readiness"

    auth.cookies.clear()
    auth.post(
        "/api/auth/login",
        json={"email": viewer_email, "password": "test-only-long-password"},
    )
    assert auth.get(path).status_code == 200
    auth.cookies.clear()
    auth.post(
        "/api/auth/login",
        json={"email": owner_email, "password": "test-only-long-password"},
    )
    issued = auth.post(
        f"/api/projects/{project_id}/agents",
        json={"name": "readiness", "scopes": ["outreach:read"]},
    )
    assert issued.status_code == 201
    response = auth.get(path, headers={"Authorization": f"Bearer {issued.json()['token']}"})
    assert response.status_code == 403


def test_form_dm_readiness_hides_other_projects(auth, form_source, users, db):
    project = form_source[0]
    auth.cookies.clear()
    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/projects/{project.id}/form-dm-readiness").status_code == 404


def test_reason_reanalysis_uses_only_snapshot_matches_and_reports_progress(auth, form_source, db):
    from app.models import OperationJob

    project, company, _draft, profile, _sender, _fields = form_source
    company_id = company.id
    profile.compatibility_reason_code = "MULTIPART_OR_FILE"
    db.commit()

    project_id = aggregate(auth, db, project)
    response = auth.post(
        f"/api/projects/{project_id}/form-dm-readiness/reanalyze?reason=MULTIPART_ONLY"
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["operation_type"] == "site_analysis"
    assert body["total_count"] == 1
    assert body["readiness_reanalysis_reason"] == "MULTIPART_ONLY"
    assert body["readiness_reanalysis_matched_count"] == 1
    job = db.get(OperationJob, body["id"])
    assert job.payload["company_ids"] == [str(company_id)]
    assert job.payload["force"] is True
    assert job.payload["readiness_reanalysis_snapshot_job_id"]
    assert job.status == "queued"

    readiness = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()
    assert readiness["active_reanalysis_job"]["id"] == str(job.id)
    job.status = "running"
    job.processed_count = 1
    db.commit()
    progress = auth.get(f"/api/projects/{project_id}/form-dm-readiness/reanalysis-jobs/{job.id}")
    assert progress.status_code == 200, progress.text
    assert progress.json()["processed_count"] == 1
    assert progress.json()["total_count"] == 1
    assert not db.scalar(
        select(OperationJob).where(
            OperationJob.project_id == project_id,
            OperationJob.operation_type.in_(("form_delivery", "form_approval_batch")),
        )
    )


def test_reason_reanalysis_includes_secondary_captcha_matches(auth, form_source, db):
    from app.models import OperationJob

    project, company, _draft, profile, _sender, _fields = form_source
    company_id = company.id
    company.do_not_contact = True
    profile.captcha_type = "CAPTCHA_RECAPTCHA_V2"
    db.commit()
    project_id = aggregate(auth, db, project)

    response = auth.post(
        f"/api/projects/{project_id}/form-dm-readiness/reanalyze?reason=CAPTCHA_VISIBLE"
    )

    assert response.status_code == 202, response.text
    assert response.json()["readiness_reanalysis_matched_count"] == 1
    job = db.get(OperationJob, response.json()["id"])
    assert job.payload["company_ids"] == [str(company_id)]


def test_reason_reanalysis_caps_job_at_500_companies(auth, form_source, db):
    from app.models import FormDmReadinessResult, OperationJob

    project = form_source[0]
    snapshot = OperationJob(
        project_id=project.id,
        operation_type="form_dm_readiness",
        status="completed",
        payload={},
        finished_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.flush()
    companies = [
        Company(
            project_id=project.id,
            company_name=f"再解析対象{index:04d}",
            domain=f"reanalysis-{index}.example",
            source="url",
        )
        for index in range(501)
    ]
    db.add_all(companies)
    db.flush()
    profiles = [
        FormProfile(
            company_id=company.id,
            form_url=f"https://{company.domain}/contact",
            form_found=True,
            is_primary=True,
        )
        for company in companies
    ]
    db.add_all(profiles)
    db.flush()
    db.add_all(
        [
            FormDmReadinessResult(
                job_id=snapshot.id,
                company_id=company.id,
                profile_id=profile.id,
                primary_reason="MULTIPART_ONLY",
                secondary_reasons=[],
                review_queue_eligible=False,
            )
            for company, profile in zip(companies, profiles, strict=True)
        ]
    )
    db.commit()

    response = auth.post(
        f"/api/projects/{project.id}/form-dm-readiness/reanalyze?reason=MULTIPART_ONLY"
    )

    assert response.status_code == 202, response.text
    job = db.get(OperationJob, response.json()["id"])
    assert job.total_count == 500
    assert len(job.payload["company_ids"]) == 500
    assert response.json()["readiness_reanalysis_matched_count"] == 501
