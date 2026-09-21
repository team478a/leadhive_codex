from app import form_batch_routes
from app.models import Company
from app.services.form_delivery import FormField, FormPreview


def make_project_and_companies(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "一括フォーム",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "全国",
            "status": "active",
        },
    ).json()
    for url in ("https://batch-a.example", "https://batch-b.example", "https://batch-c.example"):
        auth.post(f"/api/projects/{project['id']}/collection-jobs/urls", json={"urls": [url]})
    companies = [
        db.get(Company, item["id"])
        for item in auth.get(f"/api/projects/{project['id']}/companies").json()
    ]
    for company in companies:
        company.contact_url = f"https://{company.domain}/contact"
    companies[-1].do_not_contact = True
    db.commit()
    template = auth.post(
        f"/api/projects/{project['id']}/outreach-templates",
        json={
            "name": "フォームDM",
            "channel": "form",
            "subject": "",
            "body": "お問い合わせ本文です。",
        },
    ).json()
    return project, companies, template


def test_approved_bulk_form_delivery(auth, db, monkeypatch):
    project, companies, template = make_project_and_companies(auth, db)
    created = auth.post(
        f"/api/projects/{project['id']}/form-delivery-batches",
        json={
            "template_id": template["id"],
            "company_ids": [str(company.id) for company in companies],
        },
    )
    assert created.status_code == 201
    batch = created.json()
    assert sum(item["status"] == "queued" for item in batch["items"]) == 2
    assert sum(item["status"] == "skipped" for item in batch["items"]) == 1
    preview = FormPreview(
        form_url="https://batch-a.example/contact",
        action_url="https://batch-a.example/contact",
        fields=[
            FormField(
                name="message",
                label="お問い合わせ内容",
                field_type="textarea",
                required=True,
                value="",
                options=[],
            )
        ],
    )
    monkeypatch.setattr(form_batch_routes, "inspect_form", lambda _url: preview)
    monkeypatch.setattr(form_batch_routes, "submit_form", lambda _url, _values: (preview, 200))
    assert (
        auth.post(
            f"/api/form-delivery-batches/{batch['id']}/execute", json={"confirmed": False}
        ).status_code
        == 422
    )
    executed = auth.post(
        f"/api/form-delivery-batches/{batch['id']}/execute", json={"confirmed": True, "limit": 20}
    )
    assert executed.status_code == 200
    assert sum(item["status"] == "submitted" for item in executed.json()["items"]) == 2
    assert executed.json()["status"] == "completed"
