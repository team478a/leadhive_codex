"""Durable inert confirmation review. No HTTP, public API, dispatch or worker hook."""

import json
import os
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import settings
from app.models import ApprovalRequest, AuthSession, HumanApprovalProof, OutreachAuditEvent, User
from app.project_access import project_access
from app.services import human_approval as approval
from app.services.contact_permission import evaluate_contact_permission
from app.services.controlled_confirmation_contract import review_confirmation
from app.services.form_execution_plan import ExecutionPlan, plan_hash
from app.services.human_approval import now

START = "lab confirmation review started"
RESULT = "lab confirmation review recorded"
CONSUMED = "lab confirmation review token consumed"


def guard(db, request_id, session_id):
    if not (
        settings.form_confirmation_lab_enabled
        and os.environ.get("FORM_ADAPTER_LAB") == "1"
        and not settings.outbound_enabled
        and not settings.legacy_form_delivery_enabled
        and db.scalar(select(func.current_database())).endswith("_test")
    ):
        raise HTTPException(409, "確認処理は外部送信OFFの専用試験環境だけで利用できます。")
    session = db.get(AuthSession, session_id)
    if session is None or session.expires_at <= now():
        raise HTTPException(403, "有効なHuman sessionが必要です。")
    item = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise HTTPException(404, "承認が見つかりません。")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(403, "Human userが無効です。")
    project_access(item.project_id, db, user)
    if not approval.valid_approved_payload(db, item):
        db.commit()  # Preserve expiry/revocation and its append-only evidence.
        raise HTTPException(409, "有効なHuman承認が必要です。")
    proof = db.scalar(
        select(HumanApprovalProof.id).where(
            HumanApprovalProof.request_id == item.id,
            HumanApprovalProof.user_id == item.approved_by_user_id,
            HumanApprovalProof.user_id == user.id,
            HumanApprovalProof.session_hash == session_id,
            HumanApprovalProof.payload_hash == item.payload_hash,
            HumanApprovalProof.payload_version == item.payload_version,
            HumanApprovalProof.verified_at.is_not(None),
            HumanApprovalProof.used_at.is_not(None),
        )
    )
    if not proof or item.delivery_method != "form_plan_fixture":
        raise HTTPException(409, "Human再認証済みの匿名fixture承認が必要です。")
    plan = ExecutionPlan.model_validate_json(json.dumps(item.payload_snapshot["execution_plan"]))
    if plan.adapter_id != "fixture_js_confirmation" or plan.steps[0].kind != "confirm_post":
        raise HTTPException(409, "二段階の匿名確認契約が必要です。")
    decision = evaluate_contact_permission(
        db, item.project_id, item.company_id, "form", plan.form_url
    )
    if not decision.allowed:
        raise HTTPException(409, decision.message)
    return item, plan, user


def event(db, item, name):
    return db.scalar(
        select(OutreachAuditEvent).where(
            OutreachAuditEvent.request_id == item.id, OutreachAuditEvent.event == name
        )
    )


def start(db, request_id, session_id, *, expected_hash, expected_version):
    """Single durable inspection claim, never authority to issue the first POST."""
    item, _, user = guard(db, request_id, session_id)
    if (
        item.payload_hash != expected_hash
        or type(expected_version) is not int
        or (item.payload_version != expected_version)
    ):
        raise HTTPException(409, "承認payloadが変更されています。")
    if event(db, item, START):
        raise HTTPException(409, "確認処理は既に開始されています。再試行できません。")
    review_id = uuid4()
    approval.audit(db, item, START, "HUMAN", user.id, reason=str(review_id))
    db.commit()  # Must persist before any observation is accepted.
    return review_id


def record(db, request_id, session_id, review_id, *, html, response_url, fixture_token):
    """Inspect caller-supplied synthetic evidence; not trusted live server evidence."""
    item, plan, user = guard(db, request_id, session_id)
    started = event(db, item, START)
    if not started or started.reason != str(review_id) or event(db, item, RESULT):
        raise HTTPException(409, "確認結果の再利用はできません。")
    expires = min(item.expires_at, started.timestamp + timedelta(minutes=5))
    result = review_confirmation(
        plan,
        plan,
        html,
        response_url=response_url,
        expected_hash=plan_hash(plan),
        expected_version=plan.payload_version,
        expected_token=fixture_token,
        token_payload_hash=plan_hash(plan),
        expires_at=expires,
        now=now(),
        observation_id=review_id,
        already_reviewed=frozenset(),
    )
    metadata = {
        "status": result["status"],
        "reason": result["reason"],
        "token_hash": approval.payload_hash({"token": fixture_token}),
    }
    approval.audit(
        db, item, RESULT, "HUMAN", user.id, reason=json.dumps(metadata, separators=(",", ":"))
    )
    db.commit()
    return result


def consume_review_token(db, request_id, session_id, review_id, fixture_token):
    """Atomically close an inert review token. Does not consume ApprovalRequest."""
    item, _, user = guard(db, request_id, session_id)
    started, recorded = event(db, item, START), event(db, item, RESULT)
    if not started or started.reason != str(review_id) or not recorded:
        raise HTTPException(409, "確認結果がありません。")
    data = json.loads(recorded.reason)
    if (
        started.timestamp + timedelta(minutes=5) <= now()
        or data["status"] != "REVIEW_REQUIRED"
        or data["token_hash"] != approval.payload_hash({"token": fixture_token})
        or event(db, item, CONSUMED)
    ):
        raise HTTPException(409, "確認tokenは失効・不一致・使用済みです。")
    approval.audit(db, item, CONSUMED, "HUMAN", user.id, reason=str(review_id))
    db.commit()
    return {"review_closed": True, "execution_allowed": False, "submitted": False}
