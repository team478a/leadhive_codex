def make_project(auth):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    return auth.post(
        "/api/projects",
        json={
            "project_name": "共同営業プロジェクト",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "全国",
            "status": "active",
        },
    ).json()


def login(auth, user):
    response = auth.post(
        "/api/auth/login",
        json={"email": user.email, "password": "test-only-long-password"},
    )
    assert response.status_code == 200


def test_project_member_roles_and_access(auth, users):
    project = make_project(auth)
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://shared.example"]},
    )
    company = auth.get(f"/api/projects/{project['id']}/companies").json()[0]
    member = auth.post(
        f"/api/projects/{project['id']}/members",
        json={"email": users[1].email, "role": "viewer"},
    )
    assert member.status_code == 201 and member.json()["role"] == "viewer"
    members = auth.get(f"/api/projects/{project['id']}/members").json()
    assert {item["role"] for item in members} == {"owner", "viewer"}

    login(auth, users[1])
    assert [item["id"] for item in auth.get("/api/projects").json()] == [project["id"]]
    assert auth.get(f"/api/projects/{project['id']}/company-list").status_code == 200
    assert (
        auth.patch(
            f"/api/companies/{company['id']}/sales",
            json={"status": "target", "notes": "", "next_followup_at": None},
        ).status_code
        == 404
    )
    assert (
        auth.post(
            f"/api/projects/{project['id']}/members",
            json={"email": users[0].email, "role": "editor"},
        ).status_code
        == 404
    )

    login(auth, users[0])
    updated = auth.post(
        f"/api/projects/{project['id']}/members",
        json={"email": users[1].email, "role": "editor"},
    )
    assert updated.status_code == 201 and updated.json()["role"] == "editor"

    login(auth, users[1])
    changed = auth.patch(
        f"/api/companies/{company['id']}/sales",
        json={"status": "target", "notes": "共同対応", "next_followup_at": None},
    )
    assert changed.status_code == 200 and changed.json()["status"] == "target"

    login(auth, users[0])
    assert (
        auth.delete(f"/api/projects/{project['id']}/members/{updated.json()['id']}").status_code
        == 204
    )
    login(auth, users[1])
    assert auth.get(f"/api/projects/{project['id']}").status_code == 404
