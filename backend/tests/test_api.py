from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.main import app
from app.models import AuthSession, User
from app.security import COOKIE_NAME, password_hasher, token_digest
from tests.conftest import PASSWORD

PROFILE = {
    "profile_name": "建設事業者",
    "description": "テスト",
    "search_keywords": ["建設会社"],
    "positive_keywords": ["施工実績"],
    "negative_keywords": ["個人"],
    "exclusion_keywords": ["求人媒体"],
    "scoring_rules": {"weights": {"施工実績": 12}},
    "ai_instruction": "案件の営業目的に合わせて判断",
    "default_regions": ["大阪府"],
    "active": True,
}


def project_body(profile_id):
    return {
        "project_name": "営業案件",
        "target_profile_id": profile_id,
        "sales_objective": "採用支援の提案",
        "region": "大阪府",
        "status": "draft",
    }


def test_health_and_private_routes(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}
    for path in ("/auth/me", "/projects", "/target-profiles"):
        assert client.get("/api" + path).status_code == 401
    assert client.post("/api/projects", json=project_body(str(uuid4()))).status_code == 401


def test_login_logout_revocation(client, users, db):
    for email in (users[0].email, "unknown@example.com"):
        response = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
        assert response.status_code == 401
        assert "password" not in response.text
    response = client.post(
        "/api/auth/login",
        json={
            "email": users[0].email.upper(),
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    assert "password_hash" not in response.json()
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    token = client.cookies.get(COOKIE_NAME)
    assert db.get(AuthSession, token_digest(token)) is not None
    assert db.get(AuthSession, token) is None
    assert users[0].password_hash.startswith("$argon2id$")
    assert password_hasher.verify(PASSWORD, users[0].password_hash)
    assert client.get("/api/auth/me").json()["id"] == str(users[0].id)
    assert client.post("/api/auth/logout").status_code == 204
    assert (
        client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code == 401
    )


def test_session_expiry_and_rotation(auth, users, db):
    old_token = auth.cookies.get(COOKIE_NAME)
    auth.post("/api/auth/login", json={"email": users[0].email, "password": PASSWORD})
    assert db.get(AuthSession, token_digest(old_token)) is None
    session = db.get(AuthSession, token_digest(auth.cookies.get(COOKIE_NAME)))
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert auth.get("/api/projects").status_code == 401


def test_profile_seed_crud_clone_and_protection(auth):
    seeds = auth.get("/api/target-profiles").json()
    assert {p["profile_name"] for p in seeds} == {"SNS運用事業者", "トラック・運送事業者"}
    for seed in seeds:
        assert seed["is_system"] and seed["user_id"] is None
        assert len(seed["search_keywords"]) >= 5
        assert seed["scoring_rules"]["weights"]
        assert auth.put(f"/api/target-profiles/{seed['id']}", json=PROFILE).status_code == 403
        assert auth.delete(f"/api/target-profiles/{seed['id']}").status_code == 403
    response = auth.post("/api/target-profiles", json=PROFILE)
    assert response.status_code == 201
    profile = response.json()
    path = f"/api/target-profiles/{profile['id']}"
    assert auth.get(path).json()["scoring_rules"] == PROFILE["scoring_rules"]
    assert auth.put(path, json={**PROFILE, "profile_name": "更新済"}).status_code == 200
    clone = auth.post(f"/api/target-profiles/{seeds[0]['id']}/clone").json()
    assert clone["id"] != seeds[0]["id"] and not clone["is_system"]
    assert clone["scoring_rules"] == seeds[0]["scoring_rules"]
    assert auth.delete(path).status_code == 204
    assert auth.get(path).status_code == 404


def test_project_crud_and_referenced_profile(auth):
    profile = auth.post("/api/target-profiles", json=PROFILE).json()
    body = project_body(profile["id"])
    result = auth.post("/api/projects", json=body)
    assert result.status_code == 201
    path = f"/api/projects/{result.json()['id']}"
    assert auth.get(path).json()["sales_objective"] == body["sales_objective"]
    assert (
        auth.put(path, json={**body, "sales_objective": "車両販売", "status": "active"}).status_code
        == 200
    )
    assert auth.get(path).json()["sales_objective"] == "車両販売"
    assert len(auth.get("/api/projects").json()) == 1
    assert auth.delete(f"/api/target-profiles/{profile['id']}").status_code == 409
    assert auth.delete(path).status_code == 204
    assert auth.get(path).status_code == 404
    assert auth.delete(f"/api/target-profiles/{profile['id']}").status_code == 204


def test_cross_user_access(auth, users):
    profile = auth.post("/api/target-profiles", json=PROFILE).json()
    body = project_body(profile["id"])
    project = auth.post("/api/projects", json=body).json()
    auth.post("/api/auth/login", json={"email": users[1].email, "password": PASSWORD})
    assert auth.get("/api/projects").json() == []
    assert len(auth.get("/api/target-profiles").json()) == 2
    for base, obj, payload in (("projects", project, body), ("target-profiles", profile, PROFILE)):
        path = f"/api/{base}/{obj['id']}"
        assert auth.get(path).status_code == 404
        assert auth.put(path, json=payload).status_code == 404
        assert auth.delete(path).status_code == 404
    assert auth.post(f"/api/target-profiles/{profile['id']}/clone").status_code == 404
    assert auth.post("/api/projects", json=body).status_code == 404
    system_profile = auth.get("/api/target-profiles").json()[0]
    own = auth.post("/api/projects", json=project_body(system_profile["id"])).json()
    assert auth.put(f"/api/projects/{own['id']}", json=body).status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"profile_name": "  "},
        {"search_keywords": [""]},
        {"scoring_rules": []},
        {"user_id": str(uuid4())},
        {"is_system": True},
        {"active": None},
    ],
)
def test_invalid_profile_input(auth, changes):
    assert auth.post("/api/target-profiles", json={**PROFILE, **changes}).status_code == 422


def test_invalid_projects_and_inactive_profile(auth):
    profile = auth.post("/api/target-profiles", json={**PROFILE, "active": False}).json()
    body = project_body(profile["id"])
    assert auth.post("/api/projects", json=body).status_code == 422
    for changes in (
        {"project_name": " "},
        {"sales_objective": " "},
        {"region": ""},
        {"status": "invalid"},
        {"target_profile_id": "not-a-uuid"},
    ):
        assert auth.post("/api/projects", json={**body, **changes}).status_code == 422
    assert auth.post("/api/projects", json=project_body(str(uuid4()))).status_code == 404
    assert auth.get("/api/projects?offset=-1").status_code == 422
    assert auth.get("/api/target-profiles?limit=101").status_code == 422
    assert len(auth.get("/api/target-profiles?limit=1&offset=1").json()) == 1


def test_origin_protection_and_safe_validation(auth):
    assert (
        auth.post(
            "/api/target-profiles", json=PROFILE, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        auth.post("/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    )
    response = auth.post(
        "/api/target-profiles", json=PROFILE, headers={"Origin": "http://localhost:5173"}
    )
    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    response = auth.post("/api/auth/login", json={"email": "invalid", "password": "private-value"})
    assert response.status_code == 422
    assert "private-value" not in response.text


def test_sql_injection_is_data(auth, db):
    value = "'; DROP TABLE users; --"
    response = auth.post("/api/target-profiles", json={**PROFILE, "profile_name": value})
    assert response.status_code == 201 and response.json()["profile_name"] == value
    assert db.scalar(select(func.count()).select_from(User)) == 2


def test_database_failure_is_safe(client):
    class BrokenDB:
        def execute(self, *args):
            raise OperationalError("private SQL", {}, Exception("private password"))

    app.dependency_overrides[get_db] = lambda: BrokenDB()
    response = client.get("/api/health")
    assert response.status_code == 503
    assert "private" not in response.text


def test_missing_and_malformed_ids(auth):
    assert auth.get(f"/api/projects/{uuid4()}").status_code == 404
    assert auth.get("/api/projects/bad-id").status_code == 422
    assert auth.get(f"/api/target-profiles/{UUID(int=0)}").status_code == 404
