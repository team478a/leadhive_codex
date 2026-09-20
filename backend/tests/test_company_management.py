import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Activity, Company, OperationJob


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
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [str(alpha.id)]

    by_name = auth.get(
        f"/api/projects/{project['id']}/company-list", params={"sort": "company_name"}
    ).json()["items"]
    assert len(by_name) == 2
    detail = auth.get(f"/api/companies/{beta.id}")
    assert detail.status_code == 200 and detail.json()["business_type"] == "物流会社"


def test_pagination_edit_bulk_update_and_activity_history(auth, db):
    project = make_project(auth)
    alpha, beta = add_companies(auth, db, project["id"])
    page = auth.get(
        f"/api/projects/{project['id']}/company-list", params={"limit": 1, "offset": 1}
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1

    original = auth.get(f"/api/companies/{alpha.id}").json()
    editable = {
        key: original[key]
        for key in (
            "company_name",
            "address",
            "prefecture",
            "city",
            "phone",
            "email",
            "contact_url",
            "instagram_url",
            "x_url",
            "tiktok_url",
            "facebook_url",
            "youtube_url",
            "line_url",
        )
    }
    editable["phone"] = "06-9999-9999"
    assert auth.put(f"/api/companies/{alpha.id}", json=editable).json()["phone"] == "06-9999-9999"

    bulk = auth.patch(
        f"/api/projects/{project['id']}/companies/bulk-sales",
        json={"company_ids": [str(alpha.id), str(beta.id)], "status": "target"},
    )
    assert bulk.status_code == 200
    assert {item["status"] for item in bulk.json()} == {"target"}
    assigned = auth.patch(
        f"/api/projects/{project['id']}/companies/bulk-assignee",
        json={"company_ids": [str(alpha.id), str(beta.id)], "assignee": "佐藤"},
    )
    assert assigned.status_code == 200
    assert {item["assignee"] for item in assigned.json()} == {"佐藤"}
    alpha.next_followup_at = datetime.now(timezone.utc) - timedelta(hours=1)
    beta.next_followup_at = datetime.now(timezone.utc) + timedelta(days=2)
    db.flush()
    overdue = auth.get(
        f"/api/projects/{project['id']}/company-list",
        params={"assignee": "佐", "followup": "overdue"},
    ).json()
    assert overdue["total"] == 1 and overdue["items"][0]["id"] == str(alpha.id)
    activity = auth.post(
        f"/api/companies/{alpha.id}/activities",
        json={"activity_type": "call", "note": "担当者へ電話、来週再連絡"},
    )
    assert activity.status_code == 201
    history = auth.get(f"/api/companies/{alpha.id}/activities").json()
    assert {item["activity_type"] for item in history} == {"status_change", "note", "call"}


def test_outreach_queue_prioritizes_due_work_and_records_result(auth, db):
    project = make_project(auth)
    alpha, beta = add_companies(auth, db, project["id"])
    alpha.status, alpha.assignee = "target", "佐藤"
    alpha.next_followup_at = datetime.now(timezone.utc) - timedelta(hours=1)
    beta.status = "target"
    db.flush()

    queue = auth.get(f"/api/projects/{project['id']}/outreach-queue").json()
    assert [item["company"]["id"] for item in queue] == [str(alpha.id), str(beta.id)]
    assert queue[0]["due_state"] == "overdue"
    assert queue[0]["recommended_channel"] == "email"
    assert set(queue[0]["available_channels"]) == {"email", "call"}

    followup = datetime.now(timezone.utc) + timedelta(days=3)
    response = auth.post(
        f"/api/companies/{alpha.id}/outreach",
        json={
            "channel": "email",
            "outcome": "replied",
            "note": "資料を送付し、担当者から返信あり",
            "next_followup_at": followup.isoformat(),
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "replied"
    history = auth.get(f"/api/companies/{alpha.id}/activities").json()
    assert {item["activity_type"] for item in history} == {"status_change", "email"}

    assert (
        auth.post(
            f"/api/companies/{beta.id}/outreach",
            json={"channel": "sns", "outcome": "approached", "note": "DM送信"},
        ).status_code
        == 409
    )
    beta.do_not_contact = True
    db.flush()
    queue = auth.get(f"/api/projects/{project['id']}/outreach-queue").json()
    assert [item["company"]["id"] for item in queue] == [str(alpha.id)]


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
    alpha.next_followup_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.flush()
    result = auth.get("/api/dashboard")
    assert result.status_code == 200
    data = result.json()
    assert data["total_companies"] == 2
    assert data["ranks"] == {"A": 1, "B": 1}
    assert data["statuses"]["target"] == 1
    assert data["recent_jobs"][0]["source"] == "csv"
    assert data["overdue_followups"] == 1


def test_sales_activity_analytics_by_period_and_assignee(auth, db):
    project = make_project(auth)
    alpha, _ = add_companies(auth, db, project["id"])
    alpha.assignee = "佐藤"
    db.flush()
    for status in ("approached", "replied", "meeting", "won"):
        response = auth.patch(
            f"/api/companies/{alpha.id}/sales",
            json={"status": status, "notes": "", "next_followup_at": None},
        )
        assert response.status_code == 200
    auth.post(
        f"/api/companies/{alpha.id}/activities",
        json={"activity_type": "call", "note": "成果確認の電話"},
    )

    response = auth.get("/api/sales-activity-analytics", params={"days": 30})
    assert response.status_code == 200
    data = response.json()
    assert data["activities"] == 5
    assert data["approached"] == data["replied"] == data["meetings"] == data["won"] == 1
    assert data["reply_rate"] == data["meeting_rate"] == data["win_rate"] == 100.0
    assert data["by_assignee"] == [
        {"assignee": "佐藤", "approached": 1, "replied": 1, "meetings": 1, "won": 1}
    ]
    assert auth.get("/api/sales-activity-analytics", params={"days": 0}).status_code == 422


def test_data_quality_summary_and_reanalysis_queue(auth, db):
    project = make_project(auth)
    alpha, beta = add_companies(auth, db, project["id"])
    alpha.analysis_status = "failed"
    alpha.analysis_error = "取得失敗"
    alpha.address = ""
    alpha.phone = ""
    alpha.email = ""
    alpha.contact_url = ""
    beta.analysis_status = "completed"
    beta.scraped_at = datetime.now(timezone.utc) - timedelta(days=120)
    db.flush()

    quality = auth.get(f"/api/projects/{project['id']}/data-quality", params={"stale_days": 90})
    assert quality.status_code == 200
    data = quality.json()
    assert data["total"] == 2
    assert data["missing_address"] == 1 and data["missing_contact"] == 1
    assert data["failed_analysis"] == 1 and data["stale_analysis"] == 1
    assert data["reanalyzable"] == 2

    queued = auth.post(
        f"/api/projects/{project['id']}/data-quality/reanalyze",
        json={"scope": "failed_or_stale", "stale_days": 90},
    )
    assert queued.status_code == 202
    job = db.scalar(select(OperationJob).where(OperationJob.id == queued.json()["id"]))
    assert job.operation_type == "web_analysis" and job.payload["force"] is True
    assert set(job.payload["company_ids"]) == {str(alpha.id), str(beta.id)}
    assert (
        auth.post(
            f"/api/projects/{project['id']}/data-quality/reanalyze",
            json={"scope": "failed", "stale_days": 90},
        ).status_code
        == 409
    )


def test_duplicate_candidates_and_safe_merge(auth, db):
    project = make_project(auth)
    alpha, beta = add_companies(auth, db, project["id"])
    assert (
        auth.post(
            f"/api/projects/{project['id']}/companies/merge",
            json={"target_id": str(alpha.id), "source_id": str(beta.id)},
        ).status_code
        == 409
    )
    beta.phone = alpha.phone
    alpha.email = ""
    alpha.notes = "残す企業のメモ"
    beta.notes = "統合元のメモ"
    db.add(Activity(company_id=beta.id, activity_type="call", note="統合前の電話履歴"))
    db.flush()

    candidates = auth.get(f"/api/projects/{project['id']}/duplicate-candidates")
    assert candidates.status_code == 200
    pair = candidates.json()[0]
    assert "phone" in pair["reasons"]
    assert {pair["left"]["id"], pair["right"]["id"]} == {str(alpha.id), str(beta.id)}

    merged = auth.post(
        f"/api/projects/{project['id']}/companies/merge",
        json={"target_id": str(alpha.id), "source_id": str(beta.id)},
    )
    assert merged.status_code == 200
    assert merged.json()["id"] == str(alpha.id)
    assert merged.json()["email"] == "b@example.jp"
    assert "残す企業のメモ" in merged.json()["notes"]
    assert "統合元のメモ" in merged.json()["notes"]
    assert auth.get(f"/api/companies/{beta.id}").status_code == 404
    activities = auth.get(f"/api/companies/{alpha.id}/activities").json()
    assert any(item["note"] == "統合前の電話履歴" for item in activities)
    assert any("重複企業" in item["note"] for item in activities)
    assert auth.get(f"/api/projects/{project['id']}/duplicate-candidates").json() == []


def test_saved_filters_and_assignee_analytics(auth, db):
    project = make_project(auth)
    alpha, beta = add_companies(auth, db, project["id"])
    filters = {
        "rank": "A",
        "minScore": "70",
        "region": "大阪",
        "status": "approached",
        "source": "csv",
        "keyword": "採用",
        "assignee": "佐藤",
        "followup": "overdue",
        "sort": "score_desc",
    }
    created = auth.post(
        f"/api/projects/{project['id']}/saved-company-filters",
        json={"name": "佐藤担当の期限超過", "filters": filters},
    )
    assert created.status_code == 201
    assert created.json()["filters"] == filters
    listed = auth.get(f"/api/projects/{project['id']}/saved-company-filters")
    assert [item["name"] for item in listed.json()] == ["佐藤担当の期限超過"]
    filters["rank"] = "B"
    updated = auth.put(
        f"/api/saved-company-filters/{created.json()['id']}",
        json={"name": "田中担当のBランク", "filters": filters},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "田中担当のBランク"
    assert updated.json()["filters"]["rank"] == "B"

    alpha.assignee, alpha.status = "佐藤", "approached"
    alpha.next_followup_at = datetime.now(timezone.utc) - timedelta(hours=1)
    beta.assignee, beta.status = "田中", "won"
    db.flush()
    analytics = auth.get(f"/api/projects/{project['id']}/assignee-analytics")
    assert analytics.status_code == 200
    by_assignee = {item["assignee"]: item for item in analytics.json()}
    assert by_assignee["佐藤"] == {
        "assignee": "佐藤",
        "total": 1,
        "approached": 1,
        "replied": 0,
        "meetings": 0,
        "won": 0,
        "overdue": 1,
    }
    assert by_assignee["田中"]["won"] == 1

    deleted = auth.delete(f"/api/saved-company-filters/{created.json()['id']}")
    assert deleted.status_code == 204
    assert auth.get(f"/api/projects/{project['id']}/saved-company-filters").json() == []


def test_contact_suppression_blocks_recollection_and_tracks_quality(auth, db):
    project = make_project(auth)
    alpha, _ = add_companies(auth, db, project["id"])
    assert (
        auth.patch(
            f"/api/companies/{alpha.id}/contact-control",
            json={
                "do_not_contact": True,
                "exclusion_reason": "",
                "contact_quality_status": "verified",
            },
        ).status_code
        == 422
    )
    response = auth.patch(
        f"/api/companies/{alpha.id}/contact-control",
        json={
            "do_not_contact": True,
            "exclusion_reason": "連絡拒否",
            "contact_quality_status": "verified",
        },
    )
    assert response.status_code == 200
    assert response.json()["do_not_contact"] is True
    assert response.json()["status"] == "excluded"
    assert response.json()["contact_quality_status"] == "verified"
    assert (
        auth.patch(
            f"/api/companies/{alpha.id}/sales",
            json={"status": "approached", "notes": "", "next_followup_at": None},
        ).status_code
        == 409
    )

    db.delete(alpha)
    db.commit()
    recollected = auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://alpha.example"]},
    )
    assert recollected.status_code == 201
    assert recollected.json()["saved_count"] == 0
    assert recollected.json()["duplicate_count"] == 1
