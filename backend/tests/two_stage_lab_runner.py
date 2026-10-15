"""Test-only coordinator. No production worker, API or real outbound delivery."""

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.models import ApprovalRequest, FormDispatchLimits, OutreachAuditEvent
from app.services import approved_form
from app.services import controlled_confirmation_review as review
from app.services import human_approval as approval
from app.services.sending_window import allowed
from app.services.two_stage_lab_contract import bind, validate_current

FIRST = "lab two stage confirm attempted"
FINAL = "lab two stage final attempted"
RESULT = "lab two stage result"


def finish(db, request_id, outcome):
    db.rollback()
    item = db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
    )
    if not review.event(db, item, RESULT):
        approval.audit(db, item, RESULT, "SYSTEM", None, reason=outcome)
        db.commit()
    return outcome


def stage_guard(db, plan, session_id):
    approved_form.lock(db)
    validate_current(db, plan, session_id)
    item = db.get(ApprovalRequest, plan.approval_id)
    if (
        approved_form.duplicate(db, item.company_id, item.form_url)
        or not approved_form.capacity(db)
        or not allowed(db)
    ):
        raise HTTPException(409, "重複・送信上限・送信時間の確認で停止しました。")
    starts = db.scalars(
        select(OutreachAuditEvent).where(
            OutreachAuditEvent.event == FIRST,
            OutreachAuditEvent.request_id != item.id,
            OutreachAuditEvent.timestamp >= approval.now() - timedelta(days=1),
        )
    ).all()
    limits = db.get(FormDispatchLimits, 1, populate_existing=True)
    if (
        len(starts) >= limits.daily_limit
        or sum(e.timestamp >= approval.now() - timedelta(hours=1) for e in starts)
        >= limits.hourly_limit
        or any(
            e.timestamp > approval.now() - timedelta(seconds=limits.minimum_interval_seconds)
            for e in starts
        )
        or db.scalar(
            select(OutreachAuditEvent.id)
            .join(ApprovalRequest)
            .where(
                OutreachAuditEvent.event == FIRST,
                ApprovalRequest.id != item.id,
                ApprovalRequest.form_url == item.form_url,
            )
            .limit(1)
        )
    ):
        raise HTTPException(409, "管理用試行の上限・共有宛先保護で停止しました。")
    return item


def run(db, request_id, session_id, transport):
    """Transport exists only under tests and pins fixed URLs to a local fixture."""
    approved_form.lock(db)
    plan = bind(db, request_id, session_id)
    stage_guard(db, plan, session_id)
    review_id = review.start(
        db,
        request_id,
        session_id,
        expected_hash=plan.approval_hash,
        expected_version=plan.execution_plan.payload_version,
    )
    try:
        item = stage_guard(db, plan, session_id)
        approval.audit(db, item, FIRST, "SYSTEM", None, reason=str(review_id))
        db.commit()  # Conservative UNKNOWN evidence before the first synthetic POST.
        evidence = transport.confirm(plan, review_id)
        if evidence is None:
            review.record(
                db,
                request_id,
                session_id,
                review_id,
                html=None,
                response_url=plan.execution_plan.steps[0].url,
                fixture_token="",
            )
            return finish(db, request_id, "UNKNOWN")
        if (
            evidence["attempt_id"] != str(review_id)
            or evidence["form_id"] != plan.execution_plan.form_id
            or evidence["payload_hash"] != plan.approval_hash
        ):
            return finish(db, request_id, "UNKNOWN")
        token_expires = datetime.fromisoformat(evidence["expires_at"])
        if (
            token_expires.tzinfo is None
            or not approval.now() < token_expires <= approval.now() + timedelta(minutes=5)
        ):
            return finish(db, request_id, "BLOCKED")
        result = review.record(
            db,
            request_id,
            session_id,
            review_id,
            html=evidence["html"],
            response_url=plan.execution_plan.steps[0].url,
            fixture_token=evidence["token"],
        )
        if result["status"] != "REVIEW_REQUIRED":
            return finish(db, request_id, result["status"])
        if token_expires <= approval.now():
            return finish(db, request_id, "BLOCKED")
        item = stage_guard(db, plan, session_id)
        approval.audit(db, item, FINAL, "SYSTEM", None, reason=str(review_id))
        # Token consumption and FINAL marker commit atomically before the final POST.
        review.consume_review_token(db, request_id, session_id, review_id, evidence["token"])
        result = (
            "FIXTURE_SUBMITTED"
            if transport.submit(plan, review_id, evidence["token"])
            else "UNKNOWN"
        )
        return finish(db, request_id, result)
    except HTTPException:
        db.rollback()
        return finish(db, request_id, "BLOCKED")
    except Exception:
        db.rollback()
        return finish(db, request_id, "UNKNOWN")
