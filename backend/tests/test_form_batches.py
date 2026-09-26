from contextlib import nullcontext

from app import worker
from app.models import Company, FormProfile, FormProfileField
from app.services import bulk_form_delivery, form_profile_delivery
from app.services.form_delivery import FormField, FormPreview, FormSubmissionResult


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


def add_ready_profiles(db, companies):
    profiles = []
    for company in companies:
        profile = FormProfile(
            company_id=company.id,
            form_url=company.contact_url,
            form_index=0,
            form_status="READY",
            sales_contact_status="ALLOWED",
            captcha_type="CAPTCHA_NONE",
            confirmation_page=False,
            is_primary=True,
            form_found=True,
            fingerprint="f" * 64,
        )
        db.add(profile)
        db.flush()
        db.add(
            FormProfileField(
                form_profile_id=profile.id,
                position=0,
                name="message",
                field_type="textarea",
                required=True,
                mapped_key="message",
                confidence=0.95,
            )
        )
        profiles.append(profile)
    db.commit()
    return profiles


def test_approved_bulk_form_delivery(auth, db, monkeypatch):
    project, companies, template = make_project_and_companies(auth, db)
    profiles = add_ready_profiles(db, companies[:2])
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
                    mapped_key="message",
                    confidence=0.95,
                    decision_source="RULE",
                )
        ],
        form_status="READY",
        fingerprint="f" * 64,
    )
    monkeypatch.setattr(form_profile_delivery, "inspect_form", lambda _url, **_kwargs: preview)
    monkeypatch.setattr(
        bulk_form_delivery,
        "submit_form",
        lambda _url, _values, **_kwargs: (
            preview,
            FormSubmissionResult(200, "https://batch-a.example/thanks", False, "完了URL"),
        ),
    )
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
    submitted_urls = {
        item["form_url"] for item in completed["items"] if item["status"] == "submitted"
    }
    assert submitted_urls == {profile.form_url for profile in profiles}


def test_failed_form_batch_item_can_be_requeued(auth, db, monkeypatch):
    project, companies, template = make_project_and_companies(auth, db)
    add_ready_profiles(db, companies[:1])
    batch = auth.post(
        f"/api/projects/{project['id']}/form-delivery-batches",
        json={"template_id": template["id"], "company_ids": [str(companies[0].id)]},
    ).json()
    monkeypatch.setattr(
        form_profile_delivery,
        "inspect_form",
        lambda _url, **_kwargs: (_ for _ in ()).throw(RuntimeError("temporary failure")),
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
    assert batch["items"][0]["status"] == "manual_required"
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
