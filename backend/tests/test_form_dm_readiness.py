from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models import FormProfile, FormProfileField, ProjectMember
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
    assert "company_name" in exported.text
    assert company_name in exported.text


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


def test_form_dm_readiness_classifies_prohibition_before_captcha(auth, form_source, db):
    project, company, _draft, profile, _sender, _fields = form_source
    company.do_not_contact = True
    profile.captcha_type = "CAPTCHA_RECAPTCHA"
    project_id = aggregate(auth, db, project)

    result = auth.get(f"/api/projects/{project_id}/form-dm-readiness").json()

    assert result["counts"]["CONTACT_PROHIBITED"] == 1
    assert result["items"][0]["primary_reason"] == "CONTACT_PROHIBITED"
    assert result["items"][0]["secondary_reasons"] == ["CAPTCHA"]


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
