from app.models import FormProfile, ProjectMember
from tests.test_approval_foundation import workspace as workspace  # noqa: F401
from tests.test_form_approval_preparation import form_source as form_source


def test_form_dm_readiness_is_read_only_and_exports_csv(auth, form_source, db):
    project, company, _draft, profile, _sender, _fields = form_source
    before = profile.updated_at

    result = auth.get(f"/api/projects/{project.id}/form-dm-readiness")

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["counts"]["READY"] == 1
    assert body["total"] == 1
    assert body["items"][0]["company_id"] == str(company.id)
    assert body["items"][0]["primary_reason"] == "READY"
    assert body["read_only"] is True
    assert body["external_requests"] == 0
    db.expire_all()
    assert db.get(FormProfile, profile.id).updated_at == before

    exported = auth.get(f"/api/projects/{project.id}/form-dm-readiness?format=csv")
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "company_name" in exported.text
    assert company.company_name in exported.text


def test_form_dm_readiness_classifies_prohibition_before_captcha(auth, form_source):
    project, company, _draft, profile, _sender, _fields = form_source
    company.do_not_contact = True
    profile.captcha_type = "CAPTCHA_RECAPTCHA"

    result = auth.get(f"/api/projects/{project.id}/form-dm-readiness").json()

    assert result["counts"]["CONTACT_PROHIBITED"] == 1
    assert result["items"][0]["primary_reason"] == "CONTACT_PROHIBITED"
    assert result["items"][0]["secondary_reasons"] == ["CAPTCHA"]


def test_form_dm_readiness_excludes_profiles_without_a_found_form(auth, form_source):
    project, _company, _draft, profile, _sender, _fields = form_source
    profile.form_found = False

    result = auth.get(f"/api/projects/{project.id}/form-dm-readiness")

    assert result.status_code == 200, result.text
    assert result.json()["total"] == 0
    assert sum(result.json()["counts"].values()) == 0


def test_form_dm_readiness_viewer_can_read_and_agent_is_not_authorized(
    auth, form_source, users, db
):
    project, _company, *_ = form_source
    db.add(ProjectMember(project_id=project.id, user_id=users[1].id, role="viewer"))
    db.commit()
    path = f"/api/projects/{project.id}/form-dm-readiness"

    auth.cookies.clear()
    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(path).status_code == 200
    auth.cookies.clear()
    auth.post(
        "/api/auth/login",
        json={"email": users[0].email, "password": "test-only-long-password"},
    )
    issued = auth.post(
        f"/api/projects/{project.id}/agents",
        json={"name": "readiness", "scopes": ["outreach:read"]},
    )
    assert issued.status_code == 201
    response = auth.get(path, headers={"Authorization": f"Bearer {issued.json()['token']}"})
    assert response.status_code == 401


def test_form_dm_readiness_hides_other_projects(auth, form_source, users, db):
    project = form_source[0]
    auth.cookies.clear()
    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/projects/{project.id}/form-dm-readiness").status_code == 404
