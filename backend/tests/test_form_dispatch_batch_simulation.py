"""50 real preparations/approvals/reservations, mocked network, interrupted worker recovery."""

from datetime import timedelta
from time import perf_counter

from sqlalchemy import func, select

from app.config import settings
from app.models import (
    ApprovedFormDispatch,
    Company,
    FormDelivery,
    FormDispatchLimits,
    FormProfile,
    FormProfileField,
    OutreachDraft,
)
from app.services import (
    approved_form as service,
)
from app.services import (
    approved_form_worker as worker,
)
from app.services import (
    human_approval as approval,
)
from app.services.form_delivery import FormDeliveryError, FormField, FormPreview
from app.services.form_delivery_result import FormSubmissionResult
from app.services.form_profile_delivery import DeliveryProfileContext
from tests.test_approval_foundation import workspace as workspace
from tests.test_approved_email import proof, selection
from tests.test_form_approval_preparation import form_source as form_source
from tests.test_form_approval_preparation import prepare
from tests.test_form_site_rate import record


def test_50_prepared_approved_reserved_mock_dispatches(auth, form_source, db, monkeypatch):
    tick = perf_counter()
    project = form_source[0]
    items = []
    for number in range(50):
        url = f"https://company-{number}.example/contact"
        company = Company(
            project_id=project.id,
            source="url",
            company_name=f"Synthetic {number}",
            website_url=f"https://company-{number}.example",
            domain=f"company-{number}.example",
            contact_url=url,
        )
        db.add(company)
        db.flush()
        profile = FormProfile(
            company_id=company.id,
            form_url=url,
            action_url=f"https://forms-{number // 5}.example/post/{number}",
            form_status="READY",
            sales_contact_status="ALLOWED",
            captcha_type="CAPTCHA_NONE",
            confirmation_page=False,
            form_found=True,
            delivery_supported=True,
            fingerprint="a" * 64,
            is_primary=True,
        )
        db.add(profile)
        db.flush()
        db.add_all(
            [
                FormProfileField(
                    form_profile_id=profile.id,
                    position=i,
                    name=name,
                    label=name,
                    field_type=kind,
                    required=True,
                    mapped_key=key,
                    confidence=1.0,  # Explicit, known synthetic mapping; not production inference.
                )
                for i, (name, kind, key) in enumerate(
                    [("email", "email", "email"), ("message", "textarea", "message")]
                )
            ]
        )
        draft = OutreachDraft(
            company_id=company.id,
            channel="form",
            subject="Mock proposal",
            body=f"Mock body {number}",
        )
        db.add(draft)
        db.commit()
        items.append(prepare(auth, (project, company, draft)))
    token = proof(auth, project, items)
    assert (
        auth.post(
            f"/api/projects/{project.id}/bulk-approval/approve", json={"challenge_token": token}
        ).status_code
        == 200
    )
    from uuid import uuid4

    response = auth.post(
        f"/api/projects/{project.id}/approved-form-dispatches",
        json={"items": [selection(i) for i in items], "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    assert all(r["reservation"] and not r["error"] for r in response.json()["results"])
    prepared_seconds = perf_counter() - tick
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    limits = db.get(FormDispatchLimits, 1)
    limits.daily_limit, limits.hourly_limit = 500, 100
    db.commit()
    clock = [approval.now()]
    monkeypatch.setattr(approval, "now", lambda: clock[0])

    def inspect(db, company, draft):
        profile = db.scalar(select(FormProfile).where(FormProfile.company_id == company.id))
        fields = db.scalars(
            select(FormProfileField).where(FormProfileField.form_profile_id == profile.id)
        ).all()
        preview = FormPreview(
            profile.form_url,
            profile.action_url,
            [
                FormField(f.name, f.label, f.field_type, f.required, "", [], f.mapped_key)
                for f in fields
            ],
            profile.id,
            "READY",
            profile.fingerprint,
        )
        return DeliveryProfileContext(profile, fields, preview, {})

    monkeypatch.setattr(worker, "inspect_delivery_profile", inspect)
    calls = []

    def submit(url, values, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise FormDeliveryError("mock response unknown", submission_unknown=True)
        if len(calls) == 2:
            raise FormDeliveryError("mock pre-POST field mismatch")
        return None, FormSubmissionResult(200, url + "/thanks", False, "mock success")

    monkeypatch.setattr(worker, "submit_form", submit)
    for number in range(50):
        row = service.claim(db)
        assert row, number
        company = db.get(Company, row.company_id)
        if number == 0:  # Process disappears before POST.
            clock[0] = row.lease_expires_at + timedelta(seconds=1)
            continue
        if number == 1:  # Durable UNKNOWN survives a process death after consume.
            worker.begin(db, row.id, row.worker_id, inspect(db, company, None))
            db.rollback()
        else:
            if number == 3:
                company.do_not_contact = True
                db.commit()
            worker.run(db, row)
        clock[0] += timedelta(seconds=600)
    assert service.claim(db) is None
    counts = dict(
        db.execute(
            select(ApprovedFormDispatch.status, func.count()).group_by(ApprovedFormDispatch.status)
        ).all()
    )
    assert counts == {"blocked": 2, "unknown": 2, "failed": 1, "submitted": 45}
    assert len(calls) == len(set(calls)) == 47
    assert db.scalar(select(func.count()).select_from(FormDelivery)) == 48
    record(
        {
            "scenario": "human_approved_mock_batch",
            "prepared": 50,
            "counts": counts,
            "prepare_approve_reserve_seconds": round(prepared_seconds, 3),
            "total_seconds": round(perf_counter() - tick, 3),
            "mock_submit_calls": len(calls),
            "duplicate_mock_calls": 0,
            "external_requests": 0,
            "virtual_clock": True,
            "full_3000_dispatch_test": False,
        }
    )
