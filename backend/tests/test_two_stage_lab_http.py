from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import settings
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    EmailDelivery,
    FormDelivery,
    FormDispatchLimits,
    OutreachAuditEvent,
)
from app.security import COOKIE_NAME, token_digest
from app.services.form_adapter_contract import digest
from app.services.two_stage_lab_contract import bind, canonical
from tests.test_approval_foundation import approve, challenge
from tests.test_approval_foundation import workspace as workspace
from tests.test_form_approval_preparation import form_source as form_source
from tests.test_multipart_human_approval_boundary import proposal
from tests.two_stage_lab_http import PinnedTwoStageTransport, TwoStageServer, TwoStageTransport
from tests.two_stage_lab_runner import FINAL, FIRST, run


@pytest.fixture
def source(auth, form_source, db, monkeypatch, legacy_delivery_test_mode):
    monkeypatch.setenv("FORM_ADAPTER_LAB", "1")
    monkeypatch.setattr(settings, "form_confirmation_lab_enabled", True)
    monkeypatch.setattr(settings, "outbound_enabled", False)
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)
    project, company, draft, profile, sender, _ = form_source
    data = proposal((project, company))
    data["source_draft_id"] = str(draft.id)
    data["execution_plan"]["route_fingerprint"] = digest(
        {
            "confirm": "https://fixture.example/confirm",
            "submit": "https://fixture.example/submit",
        }
    )
    draft.subject, draft.body = data["subject"], data["body"]
    sender.contact_name, sender.email = "Human", "fixture@example.com"
    company.contact_url = profile.form_url = data["form_url"]
    profile.action_url = "https://fixture.example/confirm"
    profile.confirmation_page = True
    db.commit()
    response = auth.post(f"/api/projects/{project.id}/approval-requests", json=data)
    assert response.status_code == 201, response.text
    item = response.json()
    return item, token_digest(auth.cookies.get(COOKIE_NAME)), form_source


def approved(auth, source):
    assert approve(auth, source[0], challenge(auth, source[0])).status_code == 200


def safety(db, item):
    assert db.get(ApprovalRequest, item["id"]).status in {"APPROVED", "REVOKED", "EXPIRED"}
    for model in (ApprovedFormDispatch, FormDelivery, EmailDelivery):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert not settings.outbound_enabled and not settings.legacy_form_delivery_enabled


@pytest.mark.parametrize(
    "mode,expected,posts",
    [
        ("success", "FIXTURE_SUBMITTED", 2),
        ("changed_values", "BLOCKED", 1),
        ("wrong_binding", "UNKNOWN", 1),
        ("wrong_form", "UNKNOWN", 1),
        ("wrong_hash", "UNKNOWN", 1),
        ("expired_token", "BLOCKED", 1),
        ("ambiguous", "UNKNOWN", 2),
    ],
)
def test_bound_multipart_roundtrip_and_no_replay(auth, source, db, mode, expected, posts):
    approved(auth, source)
    item, session, _ = source

    def before_post(stage):
        marker = FIRST if stage == "confirm" else FINAL
        assert db.scalar(
            select(OutreachAuditEvent.id).where(
                OutreachAuditEvent.request_id == item["id"],
                OutreachAuditEvent.event == marker,
            )
        )

    with TwoStageServer(mode) as lab:
        transport = TwoStageTransport(lab.port, before_post=before_post)
        assert run(db, item["id"], session, transport) == expected
        assert len(lab.posts) == posts
        assert lab.accepted == (1 if posts == 2 else 0)
        with pytest.raises(HTTPException):
            run(db, item["id"], session, transport)
        assert len(lab.posts) == posts
    safety(db, item)


@pytest.mark.parametrize(
    "change", ["draft", "sender", "profile", "suppression", "captcha", "limit", "flag"]
)
def test_change_after_confirmation_stops_final_post(auth, source, db, monkeypatch, change):
    approved(auth, source)
    item, session, saved = source

    def mutate():
        if change == "draft":
            saved[2].body = "changed"
        elif change == "sender":
            saved[4].email = "other@example.com"
        elif change == "profile":
            saved[3].fingerprint = "c" * 64
        elif change == "suppression":
            saved[1].do_not_contact = True
        elif change == "captcha":
            saved[3].captcha_type = "CAPTCHA_RECAPTCHA"
        elif change == "limit":
            db.get(FormDispatchLimits, 1).paused = True
        elif change == "flag":
            monkeypatch.setattr(settings, "form_confirmation_lab_enabled", False)
        db.commit()

    with TwoStageServer() as lab:
        assert (
            run(db, item["id"], session, TwoStageTransport(lab.port, after_confirm=mutate))
            == "BLOCKED"
        )
        assert lab.posts == ["/confirm"] and lab.accepted == 0
    safety(db, item)


def test_no_human_approval_no_posts(auth, source, db):
    with TwoStageServer() as lab:
        with pytest.raises(HTTPException):
            run(db, source[0]["id"], source[1], TwoStageTransport(lab.port))
        assert not lab.posts


def test_binding_changes_and_fixed_transport(auth, source, db):
    approved(auth, source)
    plan = bind(db, source[0]["id"], source[1])
    assert plan.source_draft_id == UUID(source[0]["source_draft_id"])
    assert plan.form_profile_id == source[2][3].id
    assert canonical(plan)["approval_hash"] == source[0]["payload_hash"]
    malformed = plan.execution_plan.model_copy(update={"steps": ()})
    with pytest.raises(ValueError):
        canonical(plan.model_copy(update={"execution_plan": malformed}))
    for name in ("fixture_token", "submitFinal", "bad\r\nname"):
        fields = plan.execution_plan.field_values
        malformed = plan.execution_plan.model_copy(
            update={
                "field_values": (fields[0].model_copy(update={"name": name}), *fields[1:]),
            }
        )
        with pytest.raises(ValueError):
            canonical(plan.model_copy(update={"execution_plan": malformed}))
    with PinnedTwoStageTransport(1) as transport:
        for method, url in [
            ("POST", "https://external.example/submit"),
            ("GET", "https://fixture.example/submit"),
            ("POST", "https://fixture.example/contact"),
        ]:
            with pytest.raises(ValueError):
                transport.handle_request(httpx.Request(method, url))


@pytest.mark.parametrize("stage", ["confirm", "submit"])
def test_lost_response_never_replays(auth, source, db, stage):
    approved(auth, source)
    with TwoStageServer() as lab:
        transport = TwoStageTransport(lab.port)
        original = getattr(transport, stage)

        def lost(*args):
            original(*args)
            raise RuntimeError("Synthetic response loss after fixture POST")

        setattr(transport, stage, lost)
        assert run(db, source[0]["id"], source[1], transport) == "UNKNOWN"
        before = len(lab.posts)
        with pytest.raises(HTTPException):
            run(db, source[0]["id"], source[1], transport)
        assert len(lab.posts) == before
    safety(db, source[0])
