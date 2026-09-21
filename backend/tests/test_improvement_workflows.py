from app import collection_routes
from app.models import Company, OutreachDraft
from app.services.collection import Candidate


def make_company(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "改善機能",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://improve.example"]},
    )
    company = db.get(Company, auth.get(f"/api/projects/{project['id']}/companies").json()[0]["id"])
    company.ai_status = "completed"
    company.source_keyword = "採用支援"
    db.commit()
    return project, company


def test_ai_review_deals_and_ab_experiment(auth, db):
    project, company = make_company(auth, db)
    review = auth.put(
        f"/api/companies/{company.id}/ai-review",
        json={"verdict": "incorrect", "note": "対象外の業種"},
    )
    assert review.status_code == 200 and review.json()["verdict"] == "incorrect"
    analytics = auth.get(f"/api/projects/{project['id']}/ai-review-analytics").json()
    assert analytics == [
        {
            "source_keyword": "採用支援",
            "reviewed_count": 1,
            "correct_count": 0,
            "accuracy_rate": 0.0,
        }
    ]
    deal = auth.post(
        f"/api/companies/{company.id}/deals",
        json={
            "title": "導入提案",
            "stage": "proposal",
            "expected_amount": 500000,
            "next_step": "見積送付",
        },
    )
    assert deal.status_code == 201 and deal.json()["expected_amount"] == 500000
    assert auth.get(f"/api/companies/{company.id}/deals").json()[0]["stage"] == "proposal"
    template_a = auth.post(
        f"/api/projects/{project['id']}/outreach-templates",
        json={"name": "A案", "channel": "email", "subject": "A件名", "body": "A本文"},
    ).json()
    template_b = auth.post(
        f"/api/projects/{project['id']}/outreach-templates",
        json={"name": "B案", "channel": "email", "subject": "B件名", "body": "B本文"},
    ).json()
    experiment = auth.post(
        f"/api/projects/{project['id']}/outreach-experiments",
        json={
            "name": "件名比較",
            "template_a_id": template_a["id"],
            "template_b_id": template_b["id"],
            "active": True,
        },
    )
    assert experiment.status_code == 201
    draft = OutreachDraft(company_id=company.id, channel="email", subject="元件名", body="元本文")
    db.add(draft)
    db.commit()
    assigned = auth.post(f"/api/outreach-experiments/{experiment.json()['id']}/apply/{draft.id}")
    assert assigned.status_code == 200 and assigned.json()["variant"] in {"A", "B"}
    db.refresh(draft)
    assert draft.experiment_id is not None and draft.subject in {"A件名", "B件名"}
    results = auth.get(f"/api/outreach-experiments/{experiment.json()['id']}/results")
    assert results.status_code == 200 and [item["variant"] for item in results.json()] == ["A", "B"]


def test_gbizinfo_collection_source(auth, db, monkeypatch):
    project, _ = make_company(auth, db)
    monkeypatch.setattr(
        collection_routes,
        "search_gbizinfo",
        lambda *_args: [Candidate("gBiz株式会社", address="東京都")],
    )
    response = auth.post(
        f"/api/projects/{project['id']}/collection-jobs/search",
        json={"source": "gbizinfo", "keywords": ["gBiz"], "region": "東京都", "max_results": 10},
    )
    assert response.status_code == 201
    assert response.json()[0]["source"] == "gbizinfo" and response.json()[0]["saved_count"] == 1
