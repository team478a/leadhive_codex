from app import outreach_draft_routes
from app.models import Company
from app.services.ai import AiAnalysisError, OutreachDraftContent


class FakeProvider:
    name = "fake"
    model = "draft-v1"

    def __init__(self, error=None):
        self.error = error
        self.contexts = []

    def generate_outreach(self, context):
        self.contexts.append(context)
        if self.error:
            raise self.error
        return OutreachDraftContent(
            subject="採用支援についてのご相談",
            body="貴社の採用支援事業を拝見し、ご連絡しました。短時間の情報交換はいかがでしょうか。",
        )


def make_company(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "営業文面テスト",
            "target_profile_id": profile_id,
            "sales_objective": "採用業務の効率化サービスを提案する",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://draft.example"]},
    )
    data = auth.get(f"/api/projects/{project['id']}/companies").json()[0]
    company = db.get(Company, data["id"])
    company.email = "contact@draft.example"
    company.business_summary = "企業向けの採用支援事業"
    company.ai_status = "completed"
    company.ai_summary = "採用支援を提供している企業"
    company.ai_strengths = ["法人向けサービス"]
    company.ai_concerns = ["導入状況は不明"]
    company.ai_recommended_approach = "採用業務の効率化について情報交換を提案"
    db.flush()
    return project, company


def test_generate_edit_list_delete_and_viewer_access(auth, users, db, monkeypatch):
    project, company = make_company(auth, db)
    provider = FakeProvider()
    monkeypatch.setattr(outreach_draft_routes, "get_ai_provider", lambda: provider)

    generated = auth.post(
        f"/api/companies/{company.id}/outreach-drafts/generate",
        json={"channel": "email", "instruction": "初回連絡なので短く"},
    )
    assert generated.status_code == 201
    draft = generated.json()
    assert draft["subject"] == "採用支援についてのご相談"
    assert draft["ai_provider"] == "fake" and draft["ai_model"] == "draft-v1"
    assert provider.contexts[0].company_name == company.company_name
    assert provider.contexts[0].sales_objective == "採用業務の効率化サービスを提案する"
    assert provider.contexts[0].instruction == "初回連絡なので短く"

    updated = auth.put(
        f"/api/outreach-drafts/{draft['id']}",
        json={"subject": "編集した件名", "body": "人が確認して編集した本文です。"},
    )
    assert updated.status_code == 200
    assert updated.json()["subject"] == "編集した件名"
    assert len(auth.get(f"/api/companies/{company.id}/outreach-drafts").json()) == 1

    template = auth.post(
        f"/api/projects/{project['id']}/outreach-templates",
        json={
            "name": "初回メール",
            "channel": "email",
            "subject": "テンプレート件名",
            "body": "テンプレート本文です。",
        },
    )
    assert template.status_code == 201
    templates = auth.get(f"/api/projects/{project['id']}/outreach-templates").json()
    assert templates[0]["name"] == "初回メール"
    applied = auth.post(
        f"/api/outreach-drafts/{draft['id']}/apply-template",
        json={"template_id": template.json()["id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["subject"] == "テンプレート件名"

    auth.post(
        f"/api/projects/{project['id']}/members",
        json={"email": users[1].email, "role": "viewer"},
    )
    auth.post(
        "/api/auth/login",
        json={"email": users[1].email, "password": "test-only-long-password"},
    )
    assert auth.get(f"/api/companies/{company.id}/outreach-drafts").status_code == 200
    assert (
        auth.put(
            f"/api/outreach-drafts/{draft['id']}",
            json={"subject": "変更", "body": "変更を拒否される本文"},
        ).status_code
        == 404
    )
    assert auth.delete(f"/api/outreach-drafts/{draft['id']}").status_code == 404

    auth.post(
        "/api/auth/login",
        json={"email": users[0].email, "password": "test-only-long-password"},
    )
    assert auth.delete(f"/api/outreach-templates/{template.json()['id']}").status_code == 204
    assert auth.delete(f"/api/outreach-drafts/{draft['id']}").status_code == 204
    assert auth.get(f"/api/companies/{company.id}/outreach-drafts").json() == []


def test_generation_guards_contact_suppression_and_provider_errors(auth, db, monkeypatch):
    _, company = make_company(auth, db)
    company.do_not_contact = True
    db.flush()
    blocked = auth.post(
        f"/api/companies/{company.id}/outreach-drafts/generate",
        json={"channel": "email"},
    )
    assert blocked.status_code == 409

    company.do_not_contact = False
    db.flush()
    provider = FakeProvider(AiAnalysisError("AIサービスとの通信に失敗しました。"))
    monkeypatch.setattr(outreach_draft_routes, "get_ai_provider", lambda: provider)
    failed = auth.post(
        f"/api/companies/{company.id}/outreach-drafts/generate",
        json={"channel": "email"},
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == "AIサービスとの通信に失敗しました。"
