"""Site spacing and synthetic scheduling/restart load. No network is used."""

import json
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from app.models import ApprovalRequest, ApprovedFormDispatch, FormDispatchLimits, FormDispatchSite
from app.services import approved_form as service
from app.services import approved_form_worker as worker
from app.services import form_site_rate
from app.services import human_approval as approval
from tests.test_approval_foundation import workspace as workspace
from tests.test_approved_form import approved as approved
from tests.test_approved_form import executor as executor
from tests.test_approved_form import reserve
from tests.test_form_approval_preparation import form_source as form_source


def record(data):
    print("FORM_LOAD " + json.dumps(data))
    target = os.environ.get("FORM_LOAD_REPORT_PATH")
    if target:
        path = Path(target)
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        path.write_text(json.dumps([*previous, data], indent=2), encoding="utf-8")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://WWW.Example.COM.:443/a", "example.com"),
        ("http://example.com:80/b", "example.com"),
        ("https://例え.jp/contact", "xn--r8jz45g.jp"),
    ],
)
def test_site_normalization(url, expected):
    assert form_site_rate.site_keys(url, url) == [expected]


def seed_queue(db, approved, source, count):
    """Synthetic PENDING fixtures exercise scheduler only, not approval/dispatch validation."""
    original = db.get(ApprovalRequest, UUID(approved["id"]))
    base = {c.name: deepcopy(getattr(original, c.name)) for c in ApprovalRequest.__table__.columns}
    proposals, rows, links = [], [], []
    for number in range(count):
        proposal_id, dispatch_id = uuid4(), uuid4()
        # Shared display and POST host: 100 blocked rows followed by eligible hosts.
        host = "approval.example" if number < 100 else f"site-{number}.example"
        url = f"https://{host}/form-{number}"
        snapshot = {**original.payload_snapshot, "form_action_url": url + "/submit"}
        proposals.append(
            {
                **base,
                "id": proposal_id,
                "proposal_id": uuid4(),
                "status": "PENDING",
                "approved_by_user_id": None,
                "approved_at": None,
                "approved_payload_hash": None,
                "approved_payload_version": None,
            }
        )
        rows.append(
            dict(
                id=dispatch_id,
                approval_id=proposal_id,
                project_id=source[0].id,
                company_id=source[1].id,
                draft_id=source[2].id,
                created_by_user_id=original.approved_by_user_id,
                idempotency_key=uuid4(),
                request_hash="b" * 64,
                payload_snapshot=snapshot,
                payload_hash=approval.payload_hash(snapshot),
                form_url=url,
                status="queued",
                created_at=original.created_at + timedelta(microseconds=number + 1),
            )
        )
        links.append(dict(dispatch_id=dispatch_id, site_key=host))
    db.execute(insert(ApprovalRequest), proposals)
    db.execute(insert(ApprovedFormDispatch), rows)
    db.execute(insert(FormDispatchSite), links)
    db.commit()


@pytest.mark.parametrize("count", [300, 3000])
def test_large_queue_skips_busy_site_and_recovers_without_post(
    auth, approved, form_source, executor, db, monkeypatch, count
):
    started_clock = perf_counter()
    reserve(auth, approved)
    first = service.claim(db)
    worker.begin(db, first.id, first.worker_id, worker.inspect_delivery_profile())
    first_started = db.get(ApprovedFormDispatch, first.id).started_at
    db.get(FormDispatchLimits, 1).site_interval_seconds = 86400
    db.commit()
    monkeypatch.setattr(approval, "now", lambda: first_started + timedelta(seconds=60))
    seed_queue(db, approved, form_source, count)
    waiting = db.scalars(
        select(ApprovedFormDispatch).where(
            ApprovedFormDispatch.form_url == "https://approval.example/form-0"
        )
    ).all()
    assert form_site_rate.wait_times(db, waiting)[waiting[0].id] == first_started + timedelta(
        seconds=86400
    )
    seeded_seconds = perf_counter() - started_clock
    samples = []
    # Restarted preflight workers become BLOCKED. UNKNOWN evidence never becomes retryable.
    for attempt in range(20):
        tick = perf_counter()
        row = service.claim(db)
        samples.append(perf_counter() - tick)
        assert row and not row.form_url.startswith("https://approval.example/")
        lost = row.lease_expires_at
        monkeypatch.setattr(approval, "now", lambda lost=lost: lost + timedelta(seconds=1))
    service.claim(db)
    assert db.get(ApprovedFormDispatch, first.id).status == "unknown"
    assert (
        db.scalar(
            select(func.count())
            .select_from(ApprovedFormDispatch)
            .where(ApprovedFormDispatch.status == "blocked")
        )
        == 20
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.status == "CONSUMED")
        )
        == 1
    )
    record(
        {
            "scenario": "synthetic_scheduler_preflight_restart",
            "queued": count,
            "claims": 20,
            "seed_seconds": round(seeded_seconds, 3),
            "claim_mean_seconds": round(sum(samples) / len(samples), 4),
            "claim_max_seconds": round(max(samples), 4),
            "unknown_retried": 0,
            "external_requests": 0,
            "end_to_end_dispatch": False,
        }
    )


def test_site_boundary_and_immutable_links(auth, approved, executor, db, monkeypatch):
    reserve(auth, approved)
    row = service.claim(db)
    worker.begin(db, row.id, row.worker_id, worker.inspect_delivery_profile())
    at = db.get(ApprovedFormDispatch, row.id).started_at
    monkeypatch.setattr(approval, "now", lambda: at + timedelta(seconds=299))
    assert db.scalar(form_site_rate.active_sites(db).limit(1)) == "approval.example"
    monkeypatch.setattr(approval, "now", lambda: at + timedelta(seconds=300))
    assert db.scalar(form_site_rate.active_sites(db).limit(1)) is None
    link = db.scalar(select(FormDispatchSite))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.delete(link)
        db.flush()


def test_post_host_is_also_reserved(auth, approved, form_source, db):
    row = reserve(auth, approved).json()
    keys = db.scalars(
        select(FormDispatchSite.site_key).where(FormDispatchSite.dispatch_id == UUID(row["id"]))
    ).all()
    assert keys == ["approval.example"]
    assert form_site_rate.site_keys(
        "https://www.example.com/contact", "https://provider.example/post"
    ) == ["example.com", "provider.example"]


def test_setting_change_rechecked_before_begin(auth, approved, executor, db, monkeypatch):
    reserve(auth, approved)
    row = service.claim(db)
    # A separate started attempt is already tested in the scheduler scenario; force live guard here.
    monkeypatch.setattr(form_site_rate, "eligible", lambda *a: False)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        worker.begin(db, row.id, row.worker_id, worker.inspect_delivery_profile())
    db.rollback()
    assert db.get(ApprovalRequest, row.approval_id).status == "APPROVED"
