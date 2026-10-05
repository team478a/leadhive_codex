from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import outreach_draft_routes
from app.models import FormDelivery, FormDeliveryBatchItem, OutreachDraft
from app.services import bulk_form_delivery, form_profile_delivery
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_delivery import FormDeliveryError
from app.services.form_profile_delivery import DeliveryProfileContext
from app.services.form_submission_guard import reserve_form_submission
from tests.test_form_batches import add_ready_profiles, make_project_and_companies
from tests.test_form_deliveries import add_ready_profile, make_form_draft, preview


def test_unknown_direct_blocks_new_draft_and_codex(auth, db, monkeypatch):
    company, draft = make_form_draft(auth, db)
    profile = add_ready_profile(db, company)
    monkeypatch.setattr(form_profile_delivery, "inspect_form", lambda *a, **kw: preview(profile.id))
    calls = []

    def uncertain(*args, **kwargs):
        row = db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id))
        assert row.status == "unknown"  # Durable marker exists before external I/O.
        calls.append(1)
        raise FormDeliveryError("timeout", submission_unknown=True)

    monkeypatch.setattr(outreach_draft_routes, "submit_form", uncertain)
    payload = {"confirmed": True, "field_values": {"name": "人", "message": "本文"}}
    assert (
        auth.post(f"/api/outreach-drafts/{draft.id}/form-delivery", json=payload).status_code == 422
    )
    row = auth.get(f"/api/outreach-drafts/{draft.id}/form-delivery").json()
    assert row["status"] == "unknown" and row["submitted_at"] is None
    assert evaluate_contact_permission(db, company.project_id, company.id, "form").reason_code == (
        "form_result_unknown"
    )
    new = OutreachDraft(company_id=company.id, channel="form", body="新しい文面")
    db.add(new)
    db.commit()
    assert auth.post(f"/api/outreach-drafts/{new.id}/form-delivery", json=payload).status_code in (
        409,
        422,
    )
    assert auth.get(f"/api/outreach-drafts/{new.id}/form-assist?confirmed=true").status_code in (
        409,
        422,
    )
    assert calls == [1]


def test_bulk_unknown_is_not_retryable_or_in_codex_queue(auth, db, users, monkeypatch):
    project, companies, template = make_project_and_companies(auth, db)
    profiles = add_ready_profiles(db, companies)
    batch = auth.post(
        f"/api/projects/{project['id']}/form-delivery-batches",
        json={
            "template_id": template["id"],
            "company_ids": [str(companies[0].id)],
        },
    ).json()
    item = db.get(FormDeliveryBatchItem, batch["items"][0]["id"])
    earlier = auth.post(
        f"/api/projects/{project['id']}/form-delivery-batches",
        json={"template_id": template["id"], "company_ids": [str(companies[0].id)]},
    ).json()
    earlier_item = db.get(FormDeliveryBatchItem, earlier["items"][0]["id"])
    earlier_item.status = "manual_required"
    db.commit()
    draft = db.get(OutreachDraft, item.draft_id)
    context = DeliveryProfileContext(
        profiles[0], [], preview(profiles[0].id), {"name": "人", "message": draft.body}
    )
    monkeypatch.setattr(bulk_form_delivery, "inspect_delivery_profile", lambda *a: context)

    def uncertain(*args, **kwargs):
        assert item.status == "unknown" and item.form_delivery_id is not None
        raise FormDeliveryError("timeout", submission_unknown=True)

    monkeypatch.setattr(bulk_form_delivery, "submit_form", uncertain)
    assert not bulk_form_delivery.process_form_batch_item(db, item, users[0].id)
    assert item.status == "unknown"
    assert (
        auth.post(
            f"/api/form-delivery-batch-items/{item.id}/retry", json={"confirmed": True}
        ).status_code
        == 409
    )
    assert (
        auth.post(f"/api/form-codex-queue/{item.id}", json={"status": "running"}).status_code == 409
    )
    assert auth.get(f"/api/projects/{project['id']}/form-codex-queue").json() == []


def test_same_url_other_company_cannot_reserve_after_process_death(auth, db, users):
    company, draft = make_form_draft(auth, db)
    profile = add_ready_profile(db, company)
    context = SimpleNamespace(preview=preview(profile.id), profile=profile, fields=[])
    first = reserve_form_submission(db, company, draft, context, users[0].id)
    db.rollback()  # Simulate lost post-reservation transaction.
    db.expire_all()
    assert db.get(FormDelivery, first.id).status == "unknown"
    company2 = SimpleNamespace(id=users[0].id)
    draft2 = SimpleNamespace(id=uuid4())
    with pytest.raises(FormDeliveryError):
        reserve_form_submission(db, company2, draft2, context, users[0].id)


def test_prepost_failure_can_be_classified_failed(auth, db, monkeypatch):
    company, draft = make_form_draft(auth, db)
    profile = add_ready_profile(db, company)
    monkeypatch.setattr(form_profile_delivery, "inspect_form", lambda *a, **kw: preview(profile.id))

    def reject_before_post(*args, **kwargs):
        raise FormDeliveryError("必須項目不足", "validation_error")

    monkeypatch.setattr(outreach_draft_routes, "submit_form", reject_before_post)
    assert (
        auth.post(
            f"/api/outreach-drafts/{draft.id}/form-delivery", json={"confirmed": True}
        ).status_code
        == 422
    )
    assert (
        db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id)).status == "failed"
    )
