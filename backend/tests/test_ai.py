from uuid import uuid4

from app import ai_routes
from app.models import Company
from app.services.ai import AiAnalysisError, AnalysisDecision, rank_for_score


class FakeProvider:
    name = "fake"
    model = "fake-v1"

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.contexts = []

    def analyze(self, context):
        self.contexts.append(context)
        if self.error:
            raise self.error
        return self.result


def make_project(auth, objective="採用支援の提案"):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    return auth.post(
        "/api/projects",
        json={
            "project_name": "AI判定テスト",
            "target_profile_id": profile_id,
            "sales_objective": objective,
            "region": "大阪府",
            "status": "active",
        },
    ).json()


def make_analyzable_company(auth, db, project_id, url="https://ai.example"):
    auth.post(f"/api/projects/{project_id}/collection-jobs/urls", json={"urls": [url]})
    data = auth.get(f"/api/projects/{project_id}/companies").json()[0]
    company = db.get(Company, data["id"])
    company.analysis_status = "completed"
    company.business_summary = "企業向け採用支援サービスを提供"
    company.website_text = "採用ページと導入事例があります。問い合わせフォームあり。"
    db.flush()
    return data


def decision(score=84):
    return AnalysisDecision(
        score=score,
        rank="C",
        is_target=False,
        business_type="採用支援会社",
        summary="企業の採用活動を支援する会社",
        reason="採用支援と導入事例をWebサイトで確認",
        strengths=["導入事例あり", "問い合わせ先あり"],
        concerns=["従業員規模は不明"],
        recommended_approach="採用効率化の事例を示して提案",
    )


def test_ai_analysis_uses_profile_objective_and_normalizes_rank(auth, db, monkeypatch):
    project = make_project(auth)
    company = make_analyzable_company(auth, db, project["id"])
    provider = FakeProvider(decision())
    monkeypatch.setattr(ai_routes, "get_ai_provider", lambda: provider)

    response = auth.post(f"/api/companies/{company['id']}/ai-analysis", json={})

    assert response.status_code == 200
    result = response.json()
    assert result["score"] == 84 and result["rank"] == "A" and result["is_target"] is True
    assert result["ai_status"] == "completed"
    assert result["ai_provider"] == "fake" and result["ai_model"] == "fake-v1"
    assert result["ai_strengths"] == ["導入事例あり", "問い合わせ先あり"]
    assert provider.contexts[0].sales_objective == "採用支援の提案"
    assert provider.contexts[0].positive_keywords
    assert provider.contexts[0].website_text


def test_ai_analysis_failure_and_missing_web_data(auth, db, monkeypatch):
    project = make_project(auth)
    company = make_analyzable_company(auth, db, project["id"])
    provider = FakeProvider(error=AiAnalysisError("AIサービスとの通信に失敗しました。"))
    monkeypatch.setattr(ai_routes, "get_ai_provider", lambda: provider)
    failed = auth.post(f"/api/companies/{company['id']}/ai-analysis", json={}).json()
    assert failed["ai_status"] == "failed"
    assert failed["ai_error"] == "AIサービスとの通信に失敗しました。"

    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://empty.example"]},
    )
    empty = next(
        item
        for item in auth.get(f"/api/projects/{project['id']}/companies").json()
        if item["domain"] == "empty.example"
    )
    skipped = auth.post(f"/api/companies/{empty['id']}/ai-analysis", json={}).json()
    assert skipped["ai_status"] == "skipped"
    assert skipped["ai_error"] == "先にWeb解析を完了してください。"


def test_batch_ai_analysis_and_access_isolation(auth, users, db, monkeypatch):
    project = make_project(auth)
    first = make_analyzable_company(auth, db, project["id"], "https://one-ai.example")
    second = make_analyzable_company(auth, db, project["id"], "https://two-ai.example")
    monkeypatch.setattr(ai_routes, "get_ai_provider", lambda: FakeProvider(decision(65)))

    response = auth.post(
        f"/api/projects/{project['id']}/ai-analysis",
        json={"company_ids": [first["id"], second["id"]]},
    )
    assert response.status_code == 200
    assert {item["rank"] for item in response.json()} == {"B"}
    assert (
        auth.post(
            f"/api/projects/{project['id']}/ai-analysis",
            json={"company_ids": [str(uuid4())]},
        ).status_code
        == 404
    )

    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.post(f"/api/companies/{first['id']}/ai-analysis", json={}).status_code == 404
    assert auth.post(f"/api/projects/{project['id']}/ai-analysis", json={}).status_code == 404


def test_rank_thresholds_are_profile_driven_and_safe():
    assert rank_for_score(90, {"rank_thresholds": {"A": 95, "B": 70, "C": 50}}) == "B"
    assert rank_for_score(65, {"rank_thresholds": {"A": 40, "B": 80, "C": 60}}) == "B"
