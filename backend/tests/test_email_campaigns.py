from app import worker
from app.models import Company, EmailDelivery, SuppressionEntry
from app.services.email_delivery import EmailDeliveryLimits


def make_campaign_project(auth, db):
    profile_id = auth.get("/api/target-profiles").json()[0]["id"]
    project = auth.post(
        "/api/projects",
        json={
            "project_name": "メールキャンペーン",
            "target_profile_id": profile_id,
            "sales_objective": "営業支援",
            "region": "全国",
            "status": "active",
        },
    ).json()
    auth.post(
        f"/api/projects/{project['id']}/collection-jobs/urls",
        json={"urls": ["https://campaign-a.example", "https://campaign-b.example"]},
    )
    companies = [
        db.get(Company, row["id"])
        for row in auth.get(f"/api/projects/{project['id']}/companies").json()
    ]
    for company in companies:
        company.email = f"contact@{company.domain}"
    db.commit()
    template = auth.post(
        f"/api/projects/{project['id']}/outreach-templates",
        json={
            "name": "初回メール",
            "channel": "email",
            "subject": "ご相談",
            "body": "ご案内です。",
        },
    ).json()
    return project, companies, template


def test_campaign_pause_resume_followup_and_unsubscribe(auth, db, monkeypatch):
    project, companies, template = make_campaign_project(auth, db)
    assert (
        auth.post(
            f"/api/projects/{project['id']}/email-campaigns",
            json={
                "name": "9月配信",
                "template_id": template["id"],
                "company_ids": [str(company.id) for company in companies],
                "confirmed": False,
            },
        ).status_code
        == 422
    )
    created = auth.post(
        f"/api/projects/{project['id']}/email-campaigns",
        json={
            "name": "9月配信",
            "template_id": template["id"],
            "company_ids": [str(company.id) for company in companies],
            "followup_days": 3,
            "confirmed": True,
        },
    )
    assert created.status_code == 201
    campaign = created.json()
    assert campaign["queued_count"] == 2 and campaign["skipped_count"] == 0
    paused = auth.post(f"/api/email-campaigns/{campaign['id']}/pause")
    assert paused.status_code == 200 and paused.json()["queued_count"] == 2
    assert worker.claim_email_delivery(db) is None
    assert auth.post(f"/api/email-campaigns/{campaign['id']}/resume").status_code == 200
    monkeypatch.setattr(worker, "email_delivery_limits", lambda _db: EmailDeliveryLimits(100, 0))
    sent = []
    monkeypatch.setattr(worker, "send_email", lambda *args: sent.append(args))
    delivery = worker.claim_email_delivery(db)
    assert delivery is not None
    worker.run_email_delivery(db, delivery)
    delivery = db.get(EmailDelivery, delivery.id)
    sent_company = db.get(Company, delivery.company_id)
    assert sent_company.next_followup_at is not None
    assert sent and sent[0][2] == sent_company.email
    unsubscribed = auth.post(f"/api/public/unsubscribe/{delivery.unsubscribe_token}")
    assert unsubscribed.status_code == 200
    db.refresh(sent_company)
    assert sent_company.do_not_contact
    assert db.query(SuppressionEntry).filter_by(email=sent_company.email).count() == 1


def test_campaign_skips_suppressed_company(auth, db):
    project, companies, template = make_campaign_project(auth, db)
    db.add(
        SuppressionEntry(
            project_id=companies[0].project_id,
            domain=companies[0].domain,
            reason="キャンペーン対象外",
        )
    )
    db.commit()
    created = auth.post(
        f"/api/projects/{project['id']}/email-campaigns",
        json={
            "name": "抑止確認",
            "template_id": template["id"],
            "company_ids": [str(company.id) for company in companies],
            "confirmed": True,
        },
    )
    assert created.status_code == 201
    assert created.json()["queued_count"] == 1
    assert created.json()["skipped_count"] == 1
