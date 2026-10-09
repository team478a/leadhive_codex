"""Real commits before both synthetic multipart POSTs in a disposable database."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import OutreachAuditEvent
from app.services import controlled_confirmation_review as review
from tests.test_approval_foundation import workspace as workspace
from tests.test_controlled_form_process import db as db
from tests.test_form_approval_preparation import form_source as form_source
from tests.test_two_stage_lab_http import approved, safety
from tests.test_two_stage_lab_http import source as source
from tests.two_stage_lab_http import TwoStageServer, TwoStageTransport
from tests.two_stage_lab_runner import FINAL, FIRST, RESULT, run


def test_post_markers_and_token_consumption_are_committed(auth, source, db):
    approved(auth, source)
    item, session, _ = source

    def before_post(stage):
        with Session(db.get_bind()) as independent:
            events = set(
                independent.scalars(
                    select(OutreachAuditEvent.event).where(
                        OutreachAuditEvent.request_id == item["id"],
                    )
                ).all()
            )
            assert FIRST in events
            if stage == "submit":
                assert FINAL in events and review.CONSUMED in events

    with TwoStageServer() as lab:
        assert (
            run(db, item["id"], session, TwoStageTransport(lab.port, before_post=before_post))
            == "FIXTURE_SUBMITTED"
        )
        assert lab.posts == ["/confirm", "/submit"] and lab.accepted == 1
    with Session(db.get_bind()) as independent:
        assert (
            independent.scalar(
                select(OutreachAuditEvent.reason).where(
                    OutreachAuditEvent.request_id == item["id"],
                    OutreachAuditEvent.event == RESULT,
                )
            )
            == "FIXTURE_SUBMITTED"
        )
        safety(independent, item)


def test_concurrent_connections_execute_fixture_only_once(auth, source, db):
    approved(auth, source)
    item, session, _ = source
    barrier = Barrier(2)
    with TwoStageServer() as lab:

        def execute():
            with Session(db.get_bind()) as independent:
                independent.execute(text("SET LOCAL lock_timeout = '5s'"))
                barrier.wait(timeout=10)
                try:
                    return run(independent, item["id"], session, TwoStageTransport(lab.port))
                except HTTPException as exc:
                    assert exc.status_code == 409
                    return "BLOCKED"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        assert sorted(results) == ["BLOCKED", "FIXTURE_SUBMITTED"]
        assert lab.posts == ["/confirm", "/submit"] and lab.accepted == 1
    db.expire_all()
    safety(db, item)
