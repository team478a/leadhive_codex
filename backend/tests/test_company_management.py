import csv
import io

from app.models import Company


def make_project(auth, name="営業リストテスト"):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    return auth.post(
        "/api/projects",
        json={
            "project_name": name,
            "target_profile_id": profile_id,
            "sales_objective": "採用支援",
            "region": "大阪府",
            "status": "active",
        },
    ).json()


def add_companies(auth, db, project_id):
    content = (
        "company_name,website_url,phone,email,address\n"
        "=危険な数式,https://alpha.example,06-1111-1111,a@example.jp,大阪府大阪市\n"
        "株式会社ベータ,https://beta.example,03-2222-2222,b@example.jp,東京都港区\n"
    ).encode()
    response = auth.post(
        f"/api/projects/{project_id}/collection-jobs/csv",
        files={"file": ("companies.csv", content, "text/csv")},
    )
    assert response.status_code == 201
    companies = auth.get(f"/api/projects/{project_id}/companies").json()
    alpha = db.get(
        Company, next(item["id"] for item in companies if item["domain"] == "alpha.example")
    )
    beta = db.get(
        Company, next(item["id"] for item in companies if item["domain"] == "beta.example")
    )
    alpha.score, alpha.rank, alpha.business_type = 88, "A", "採用支援会社"
    alpha.ai_summary, alpha.prefecture = "採用サービスを提供", "大阪府"
    beta.score, beta.rank, beta.business_type = 62, "B", "物流会社"
    beta.ai_summary, beta.prefecture = "配送サービスを提供", "東京都"
    db.flush()
    return alpha, beta


def test_company_list_filters_sorts_and_detail(auth, db):
    project = make_project(auth)
    alpha, beta = add_companies(auth, db, project["id"])

    response = auth.get(
        f"/api/projects/{project['id']}/company-list",
        params={"rank": "A", "region": "大阪", "keyword": "採用", "sort": "score_desc"},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(alpha.id)]

    by_name = auth.get(
        f"/api/projects/{project['id']}/company-list", params={"sort": "company_name"}
    ).json()
    assert len(by_name) == 2
    detail = auth.get(f"/api/companies/{beta.id}")
    assert detail.status_code == 200 and detail.json()["business_type"] == "物流会社"


def test_sales_status_update_and_access_isolation(auth, users, db):
    project = make_project(auth)
    alpha, _ = add_companies(auth, db, project["id"])
    response = auth.patch(
        f"/api/companies/{alpha.id}/sales",
        json={"status": "approached", "notes": "9月19日に問い合わせフォームから連絡"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approached"
    assert "問い合わせフォーム" in response.json()["notes"]
    assert (
        auth.patch(
            f"/api/companies/{alpha.id}/sales", json={"status": "invalid", "notes": ""}
        ).status_code
        == 422
    )

    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/companies/{alpha.id}").status_code == 404
    assert (
        auth.patch(
            f"/api/companies/{alpha.id}/sales",
            json={"status": "won", "notes": "閲覧不可"},
        ).status_code
        == 404
    )


def test_csv_export_is_filtered_utf8_and_formula_safe(auth, db):
    project = make_project(auth)
    add_companies(auth, db, project["id"])
    response = auth.get(f"/api/projects/{project['id']}/companies.csv", params={"rank": "A"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["rank"] == "A"
    assert rows[0]["company_name"] == "'=危険な数式"


def test_dashboard_counts_and_recent_jobs(auth, db):
    project = make_project(auth)
    alpha, _ = add_companies(auth, db, project["id"])
    alpha.status = "target"
    db.flush()
    result = auth.get("/api/dashboard")
    assert result.status_code == 200
    data = result.json()
    assert data["total_companies"] == 2
    assert data["ranks"] == {"A": 1, "B": 1}
    assert data["statuses"]["target"] == 1
    assert data["recent_jobs"][0]["source"] == "csv"
