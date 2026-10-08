"""One reauthentication bound to the exact set of immutable proposals."""

import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.model_approved_email import BulkApprovalProof
from app.models import ApprovalRequest, AuthSession, OutreachAuditEvent, User
from app.project_access import project_access
from app.security import token_digest
from app.services import human_approval as approval


def denied(db, project_id, user, reason):
    db.add(
        OutreachAuditEvent(
            event="authentication denied",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            reason=reason,
        )
    )
    db.commit()


def locked_items(db, project_id, selections, user):
    project_access(project_id, db, user)
    items = db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.id.in_([s.request_id for s in selections]))
        .order_by(ApprovalRequest.id)
        .with_for_update()
    ).all()
    if len(items) != len(selections) or any(i.project_id != project_id for i in items):
        raise HTTPException(404, "提案が見つかりません。")
    if any(i.delivery_method in {"cf7_candidate_only", "cf7_real_candidate_only"} for i in items):
        raise HTTPException(409, "CF7候補は個別のHuman確認が必要です。送信はできません。")
    expected = {s.request_id: s for s in selections}
    for item in items:
        approval.expected(item, expected[item.id])
        approval.invalidate_if_needed(db, item)
    if any(i.status != "PENDING" for i in items):
        db.commit()  # Preserve invalidation and audit, never grant a partial batch.
        raise HTTPException(409, "承認待ち以外の提案があります。再取得してください。")
    return items


def challenge(db, project_id, body, user, session_hash):
    items = locked_items(db, project_id, body.items, user)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    count = db.scalar(
        select(func.count())
        .select_from(BulkApprovalProof)
        .where(BulkApprovalProof.user_id == user.id, BulkApprovalProof.expires_at > approval.now())
    )
    if count >= 5:
        raise HTTPException(429, "再認証の回数が多すぎます。5分後に再試行してください。")
    token = secrets.token_urlsafe(32)
    proof = BulkApprovalProof(
        project_id=project_id,
        user_id=user.id,
        session_hash=session_hash,
        token_hash=token_digest(token),
        items=[
            {
                "request_id": str(i.id),
                "expected_hash": i.payload_hash,
                "expected_version": i.payload_version,
            }
            for i in items
        ],
        expires_at=approval.now() + timedelta(minutes=5),
    )
    db.add(proof)
    db.commit()
    return {"challenge_token": token, "expires_at": proof.expires_at, "count": len(items)}


def bound(db, project_id, token, user, session_hash):
    proof = db.scalar(
        select(BulkApprovalProof)
        .where(BulkApprovalProof.token_hash == token_digest(token))
        .with_for_update()
    )
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == session_hash).with_for_update()
    )
    if (
        not proof
        or proof.project_id != project_id
        or proof.user_id != user.id
        or proof.session_hash != session_hash
        or proof.expires_at <= approval.now()
        or proof.used_at
        or not session
        or session.user_id != user.id
        or session.expires_at <= approval.now()
    ):
        denied(db, project_id, user, "invalid bulk step-up proof")
        raise HTTPException(403, "再認証が無効です。")
    return proof


def verify(db, project_id, body, user, session_hash):
    project_access(project_id, db, user)
    proof = bound(db, project_id, body.challenge_token, user, session_hash)
    if proof.verified_at:
        raise HTTPException(409, "再認証済みです。")
    if not approval.step_up_verifier.verify(user, body.password):
        proof.used_at = approval.now()
        db.add(
            OutreachAuditEvent(
                event="authentication denied",
                principal_type="HUMAN",
                actor_id=user.id,
                project_id=project_id,
                reason="bulk step-up failed",
            )
        )
        db.commit()
        raise HTTPException(403, "再認証に失敗しました。")
    proof.verified_at = approval.now()
    db.commit()
    return {"verified": True}


def approve(db, project_id, body, user, session_hash):
    from app.schema_approved_email import ApprovalSelection

    if not isinstance(user, User):
        raise HTTPException(403, "Human承認が必要です。")
    proof = bound(db, project_id, body.challenge_token, user, session_hash)
    if not proof.verified_at:
        denied(db, project_id, user, "bulk step-up required")
        raise HTTPException(403, "再認証が必要です。")
    items = locked_items(db, project_id, [ApprovalSelection(**i) for i in proof.items], user)
    proof.used_at = approval.now()
    for item in items:
        item.status = "APPROVED"
        item.approved_by_user_id, item.approved_at = user.id, approval.now()
        item.approved_payload_hash, item.approved_payload_version = (
            item.payload_hash,
            item.payload_version,
        )
        approval.audit(
            db, item, "approval granted", "HUMAN", user.id, "PENDING", "bulk password step-up"
        )
    db.commit()
    return {"approved_count": len(items)}
