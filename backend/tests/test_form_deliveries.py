from sqlalchemy import select

from app import outreach_draft_routes
from app.models import Activity, Company, FormDelivery, OutreachDraft
from app.services.form_delivery import FormField, FormPreview


def make_form_draft(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "フォーム送信テスト",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "東京都",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://form-delivery.example"]},
    )
    company = db.get(Company, auth.get(f"/api/projects/{project['id']}/companies").json()[0]["id"])
    company.contact_url = "https://form-delivery.example/contact"
    draft = OutreachDraft(company_id=company.id, channel="form", body="サービスのご案内です。")
    db.add(draft)
    db.commit()
    return company, draft


def preview():
    return FormPreview(
        form_url="https://form-delivery.example/contact",
        action_url="https://form-delivery.example/contact/send",
        fields=[
            FormField("name", "お名前", "text", True, "", []),
            FormField("message", "お問い合わせ内容", "textarea", True, "", []),
        ],
    )


def test_form_preview_and_confirmed_delivery(auth, db, monkeypatch):
    company, draft = make_form_draft(auth, db)
    assist = auth.get(f"/api/outreach-drafts/{draft.id}/form-assist")
    assert assist.status_code == 200
    assert assist.json()["form_url"] == company.contact_url
    assert draft.body in assist.json()["instructions"] or assist.json()["body"] == draft.body
    monkeypatch.setattr(outreach_draft_routes, "inspect_form", lambda _url: preview())
    shown = auth.get(f"/api/outreach-drafts/{draft.id}/form-preview")
    assert shown.status_code == 200 and shown.json()["fields"][0]["name"] == "name"

    calls = []
    monkeypatch.setattr(
        outreach_draft_routes,
        "submit_form",
        lambda _url, values: (calls.append(values) or preview(), 200),
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/form-delivery",
            json={"field_values": {"name": "営業担当", "message": draft.body}, "confirmed": False},
        ).status_code
        == 422
    )
    submitted = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-delivery",
        json={"field_values": {"name": "営業担当", "message": draft.body}, "confirmed": True},
    )
    assert submitted.status_code == 201 and submitted.json()["status"] == "submitted"
    assert calls == [{"name": "営業担当", "message": draft.body}]
    db.refresh(company)
    assert company.status == "approached"
    assert db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id))
    assert db.scalar(
        select(Activity).where(Activity.company_id == company.id, Activity.activity_type == "form")
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/form-delivery",
            json={"field_values": {"name": "営業担当", "message": draft.body}, "confirmed": True},
        ).status_code
        == 409
    )


def test_codex_assisted_form_delivery_result_updates_sales_status(auth, db):
    company, draft = make_form_draft(auth, db)
    blocked = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
        json={"status": "submitted", "confirmed": False},
    )
    assert blocked.status_code == 422

    pending = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
        json={"status": "pending", "note": "CAPTCHAの確認待ち", "confirmed": True},
    )
    assert pending.status_code == 201
    assert pending.json()["delivery_method"] == "codex_assisted"
    assert pending.json()["status"] == "pending"
    db.refresh(company)
    assert company.status == "unreviewed"

    submitted = auth.post(
        f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
        json={"status": "submitted", "note": "送信完了画面を確認", "confirmed": True},
    )
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["result_note"] == "送信完了画面を確認"
    db.refresh(company)
    assert company.status == "approached"
    assert db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id)).submitted_at
    assert (
        len(
            db.scalars(
                select(Activity).where(
                    Activity.company_id == company.id, Activity.activity_type == "form"
                )
            ).all()
        )
        == 2
    )
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/form-assist-delivery",
            json={"status": "submitted", "confirmed": True},
        ).status_code
        == 409
    )
