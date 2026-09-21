from contextlib import nullcontext

from app import worker
from app.models import Company
from app.services import bulk_form_delivery
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
    monkeypatch.setattr(bulk_form_delivery, "inspect_form", lambda _url: preview)
    monkeypatch.setattr(bulk_form_delivery, "submit_form", lambda _url, _values: (preview, 200))
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
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
    assert executed.json()["status"] == "running"
    assert executed.json()["operation_job_id"]
    assert worker.run_once()
    completed = auth.get(f"/api/projects/{project['id']}/form-delivery-batches").json()[0]
    assert sum(item["status"] == "submitted" for item in completed["items"]) == 2
    assert completed["status"] == "completed"


def test_failed_form_batch_item_can_be_requeued(auth, db, monkeypatch):
    project, companies, template = make_project_and_companies(auth, db)
    batch = auth.post(
        f"/api/projects/{project['id']}/form-delivery-batches",
        json={"template_id": template["id"], "company_ids": [str(companies[0].id)]},
    ).json()
    monkeypatch.setattr(
        bulk_form_delivery,
        "inspect_form",
        lambda _url: (_ for _ in ()).throw(RuntimeError("temporary failure")),
    )
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    assert (
        auth.post(
            f"/api/form-delivery-batches/{batch['id']}/execute", json={"confirmed": True}
        ).status_code
        == 200
    )
    assert worker.run_once()
    item = auth.get(f"/api/projects/{project['id']}/form-delivery-batches").json()[0]["items"][0]
    assert item["status"] == "failed"
    assert (
        auth.post(
            f"/api/form-delivery-batch-items/{item['id']}/retry", json={"confirmed": False}
        ).status_code
        == 422
    )
    retried = auth.post(
        f"/api/form-delivery-batch-items/{item['id']}/retry", json={"confirmed": True}
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "ready"
    assert retried.json()["items"][0]["status"] == "queued"


def test_codex_queue_tracks_work_and_result(auth, db, monkeypatch):
    project, companies, template = make_project_and_companies(auth, db)
    batch = auth.post(
        f"/api/projects/{project['id']}/form-delivery-batches",
        json={"template_id": template["id"], "company_ids": [str(companies[0].id)]},
    ).json()
    preview = FormPreview(
        form_url=companies[0].contact_url,
        action_url=companies[0].contact_url,
        fields=[
            FormField(
                name="name", label="お名前", field_type="text", required=True, value="", options=[]
            )
        ],
    )
    monkeypatch.setattr(bulk_form_delivery, "inspect_form", lambda _url: preview)
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))
    assert (
        auth.post(
            f"/api/form-delivery-batches/{batch['id']}/execute", json={"confirmed": True}
        ).status_code
        == 200
    )
    assert worker.run_once()
    task = auth.get(f"/api/projects/{project['id']}/form-codex-queue").json()[0]
    running = auth.post(f"/api/form-codex-queue/{task['item_id']}", json={"status": "running"})
    assert running.status_code == 200 and running.json()["codex_status"] == "running"
    assert (
        auth.post(
            f"/api/form-codex-queue/{task['item_id']}",
            json={"status": "submitted", "confirmed": False},
        ).status_code
        == 422
    )
    submitted = auth.post(
        f"/api/form-codex-queue/{task['item_id']}",
        json={"status": "submitted", "confirmed": True},
    )
    assert submitted.status_code == 200 and submitted.json()["codex_status"] == "submitted"
    item = auth.get(f"/api/projects/{project['id']}/form-delivery-batches").json()[0]["items"][0]
    assert item["status"] == "submitted" and item["form_delivery_id"]
