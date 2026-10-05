"""Real loopback HTTP + committed PostgreSQL + real worker process termination.

Opt in only with FORM_HTTP_LAB=1 and leadhive_form_http_test. Default suites skip.
Unlike transaction-isolated unit fixtures, this lab retains immutable evidence.
"""

import json
import os
import subprocess
import sys
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal, get_db
from app.main import app
from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    AuthSession,
    Company,
    FormDelivery,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    Project,
    TargetProfile,
    User,
)
from app.security import password_hasher
from app.services import (
    approved_form as service,
)
from app.services import (
    approved_form_worker as worker,
)
from app.services import (
    human_approval as approval,
)
from app.services.form_delivery import _parse_form
from app.services.scraper import ScrapeError, validate_public_url
from tests.conftest import PASSWORD
from tests.form_http_lab import ORIGIN, Lab, html, local_transport
from tests.test_approval_foundation import approve, challenge
from tests.test_approved_form import reserve
from tests.test_form_approval_preparation import prepare


@pytest.fixture(autouse=True)
def lab_only():
    if os.environ.get("FORM_HTTP_LAB") != "1":
        pytest.skip("Controlled HTTP lab is opt-in")
    if make_url(os.environ["TEST_DATABASE_URL"]).database != "leadhive_form_http_test":
        pytest.fail("Controlled HTTP lab requires its dedicated database")


@pytest.fixture
def db(lab_only):
    with SessionLocal() as session:
        yield session


@pytest.fixture
def users(db):
    user = User(
        email=f"form-http-{uuid4().hex}@example.com", password_hash=password_hasher.hash(PASSWORD)
    )
    db.add(user)
    db.commit()
    return [user]


@pytest.fixture
def client(db):
    def sessions():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = sessions
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def source(db, users):
    target = TargetProfile(user_id=users[0].id, profile_name="Controlled HTTP fixture")
    db.add(target)
    db.flush()
    project = Project(
        user_id=users[0].id,
        target_profile_id=target.id,
        project_name="Controlled HTTP lab",
        sales_objective="Synthetic test only",
        region="全国",
    )
    db.add(project)
    db.flush()
    path = f"/{uuid4().hex}/contact"
    company = Company(
        source="url",
        project_id=project.id,
        company_name="Synthetic HTTP fixture",
        website_url=ORIGIN,
        domain="form-lab.test",
        contact_url=ORIGIN + path,
    )
    db.add(company)
    db.flush()
    parsed = _parse_form(html(path), company.contact_url)
    profile = FormProfile(
        company_id=company.id,
        form_url=company.contact_url,
        action_url=parsed.action_url,
        fingerprint=parsed.fingerprint,
        form_status="READY",
        sales_contact_status="ALLOWED",
        captcha_type="CAPTCHA_NONE",
        confirmation_page=False,
        form_found=True,
        delivery_supported=True,
        is_primary=True,
    )
    db.add(profile)
    db.flush()
    db.add_all(
        [
            FormProfileField(
                form_profile_id=profile.id,
                position=i,
                name=f.name,
                label=f.label,
                field_type=f.field_type,
                required=f.required,
                mapped_key="email" if f.name == "email" else "message",
            )
            for i, f in enumerate(parsed.fields)
        ]
    )
    if not db.get(FormSenderSettings, 1):
        db.add(
            FormSenderSettings(id=1, contact_name="Synthetic sender", email="sender@example.com")
        )
    draft = OutreachDraft(
        company_id=company.id,
        channel="form",
        subject="Synthetic proposal",
        body="検証専用本文🌿" * 500,
    )
    db.add(draft)
    db.commit()
    return project, company, draft, profile


@pytest.fixture
def clock(db, users, monkeypatch):
    latest = db.scalar(select(func.max(ApprovedFormDispatch.started_at)))
    # The dedicated lab retains prior evidence; advance only the test clock.
    tick = [max(approval.now(), latest + timedelta(days=2)) if latest else approval.now()]
    # Only this synthetic Human's dedicated-lab session follows the virtual clock.
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == users[0].id)):
        session.expires_at = tick[0] + timedelta(days=1)
    db.commit()
    monkeypatch.setattr(approval, "now", lambda: tick[0])
    monkeypatch.setattr(settings, "outbound_enabled", True)
    monkeypatch.setattr(settings, "human_approved_form_enabled", True)
    monkeypatch.setattr(settings, "legacy_form_delivery_enabled", False)
    return tick


@pytest.fixture
def lab():
    with Lab() as fixture, local_transport(fixture.port):
        yield fixture


def ready(auth, source, db):
    item = prepare(auth, source)
    assert approve(auth, item, challenge(auth, item)).status_code == 200
    result = reserve(auth, item)
    assert result.status_code == 201, result.text
    return item, UUID(result.json()["id"])


@pytest.mark.parametrize("mode", ["success", "redirect_success"])
def test_real_http_success_immutable_unicode_and_hidden_token(auth, source, db, clock, lab, mode):
    lab.mode = mode
    item, row_id = ready(auth, source, db)
    assert lab.gets == 0 and lab.posts == []  # Prepare/approve/reserve never fetch or POST.
    worker.run(db, service.claim(db))
    db.expire_all()
    row = db.get(ApprovedFormDispatch, row_id)
    assert row.status == "submitted", row.reason
    assert len(lab.posts) == 1
    payload = lab.posts[0]["payload"]
    assert payload["message"] == [source[2].body] and len(source[2].body) > 2000
    assert payload["email"] == ["sender@example.com"]
    assert payload["csrf"] == ["fixture-token-2"]
    assert db.get(ApprovalRequest, UUID(item["id"])).status == "CONSUMED"
    assert db.get(FormDelivery, row.delivery_id).completion_evidence
    assert reserve(auth, item).status_code == 409
    assert service.claim(db) is None and len(lab.posts) == 1


@pytest.mark.parametrize(
    "mode", ["disconnect", "truncated", "ambiguous", "repost_redirect", "timeout"]
)
def test_accepted_but_unknown_never_reposts(auth, source, db, clock, lab, mode):
    lab.mode = mode
    item, row_id = ready(auth, source, db)
    worker.run(db, service.claim(db))
    db.expire_all()
    row = db.get(ApprovedFormDispatch, row_id)
    assert row.status == "unknown" and len(lab.posts) == 1
    assert db.get(FormDelivery, row.delivery_id).status == "unknown"
    assert db.get(ApprovalRequest, UUID(item["id"])).status == "CONSUMED"
    clock[0] += timedelta(days=2)
    for _ in range(3):
        assert service.claim(db) is None
    assert reserve(auth, item).status_code == 409 and len(lab.posts) == 1


@pytest.mark.parametrize("mode", ["changed", "captcha", "prohibited", "changed_after_inspect"])
def test_real_preflight_and_second_fetch_changes_do_not_post(auth, source, db, clock, lab, mode):
    lab.mode = mode
    _, row_id = ready(auth, source, db)
    worker.run(db, service.claim(db))
    db.expire_all()
    row = db.get(ApprovedFormDispatch, row_id)
    assert row.status == ("failed" if mode == "changed_after_inspect" else "blocked"), row.reason
    assert lab.posts == []
    assert service.claim(db) is None


def child(mode, clock, lab):
    environment = os.environ.copy()
    environment.update(FORM_HTTP_LAB_PORT=str(lab.port), FORM_HTTP_LAB_CLOCK=clock[0].isoformat())
    return subprocess.Popen(
        [sys.executable, "-m", "tests.form_http_process", mode],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def finished(process):
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, stderr
    return json.loads(stdout)


def test_two_real_claim_processes_only_one_wins(auth, source, db, clock, lab):
    _, row_id = ready(auth, source, db)
    processes = [child("claim", clock, lab), child("claim", clock, lab)]
    try:
        results = [finished(process) for process in processes]
        assert sorted(bool(result["id"]) for result in results) == [False, True]
        db.expire_all()
        row = db.get(ApprovedFormDispatch, row_id)
        worker.run(db, row)
        assert len(lab.posts) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


@pytest.mark.parametrize("stage", ["hold_preflight", "hold_accepted"])
def test_killed_worker_restart_preserves_no_retry(auth, source, db, clock, lab, stage):
    lab.mode = stage
    item, row_id = ready(auth, source, db)
    process = child("dispatch", clock, lab)
    try:
        signal = lab.preflight if stage == "hold_preflight" else lab.accepted
        assert signal.wait(15), "Child did not reach the controlled interruption point"
        process.kill()
        process.communicate(timeout=10)
        lab.release.set()
        db.expire_all()
        row = db.get(ApprovedFormDispatch, row_id)
        assert row.status == ("checking" if stage == "hold_preflight" else "unknown")
        clock[0] = row.lease_expires_at + timedelta(seconds=1)
        # New OS process with fresh connections, not a call on the killed worker's objects.
        assert finished(child("dispatch", clock, lab))["id"] is None
        db.expire_all()
        row = db.get(ApprovedFormDispatch, row_id)
        assert row.status == ("blocked" if stage == "hold_preflight" else "unknown")
        assert len(lab.posts) == (0 if stage == "hold_preflight" else 1)
        if stage == "hold_accepted":
            assert db.get(ApprovalRequest, UUID(item["id"])).status == "CONSUMED"
            assert db.get(FormDelivery, row.delivery_id).status == "unknown"
            assert reserve(auth, item).status_code == 409
    finally:
        lab.release.set()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_production_private_url_guard_remains_closed(lab):
    with pytest.raises(ScrapeError, match="プライベート"):
        validate_public_url("http://127.0.0.1/contact")
