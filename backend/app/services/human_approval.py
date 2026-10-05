"""A2 only: immutable proposals, human proofs and transactional audit events.

No executor, network client, dispatch, consume or delivery imports belong here.
"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.model_approval import ApprovalRequest, HumanApprovalProof, OutreachAuditEvent
from app.models import (
    AuthSession,
    Company,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    User,
)
from app.schema_approval import ExpectedPayload, Proposal
from app.security import password_hasher, token_digest
from app.services.form_adapter_contract import adapter_plan_hash, adapter_snapshot, canonical_plan
from app.services.form_execution_plan import plan_hash


def now():
    return datetime.now(timezone.utc)


def payload_hash(snapshot: dict) -> str:
    # json-v1: UTF-8, sorted keys, compact separators; strings are preserved exactly.
    encoded = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def audit(db, item, event, principal_type, actor_id, before=None, reason=None):
    db.add(
        OutreachAuditEvent(
            event=event,
            principal_type=principal_type,
            actor_id=actor_id,
            request_id=item.id,
            project_id=item.project_id,
            company_id=item.company_id,
            payload_hash=item.payload_hash,
            payload_version=item.payload_version,
            before_status=before,
            after_status=item.status,
            reason=reason,
        )
    )


def draft_fingerprint(draft):
    return payload_hash(
        {
            "id": str(draft.id),
            "company_id": str(draft.company_id),
            "channel": draft.channel,
            "subject": draft.subject,
            "body": draft.body,
        }
    )


def company_fingerprint(company):
    return payload_hash(
        {
            key: getattr(company, key)
            for key in (
                "company_name",
                "website_url",
                "domain",
                "email",
                "phone",
                "contact_url",
            )
        }
    )


def form_dependency_hash(db, company_id):
    # Stored analysis only. Never fetch a page or contact an external form in A2.
    profiles = db.scalars(
        select(FormProfile).where(FormProfile.company_id == company_id).order_by(FormProfile.id)
    ).all()
    data = []
    for profile in profiles:
        fields = db.scalars(
            select(FormProfileField)
            .where(FormProfileField.form_profile_id == profile.id)
            .order_by(FormProfileField.position)
        ).all()
        data.append(
            {
                "id": str(profile.id),
                "url": profile.form_url,
                "action_url": profile.action_url,
                "index": profile.form_index,
                "fingerprint": profile.fingerprint,
                "primary": profile.is_primary,
                "status": profile.form_status,
                "sales_contact_status": profile.sales_contact_status,
                "captcha": profile.captcha_type,
                "delivery_supported": profile.delivery_supported,
                "confirmation_page": profile.confirmation_page,
                "form_found": profile.form_found,
                "fields": [
                    {
                        column.name: (
                            str(getattr(field, column.name))
                            if isinstance(getattr(field, column.name), UUID)
                            else getattr(field, column.name)
                        )
                        for column in FormProfileField.__table__.columns
                        if column.name not in {"created_at", "updated_at"}
                    }
                    for field in fields
                ],
            }
        )
    return payload_hash({"profiles": data})


def form_sender_hash(db):
    sender = db.get(FormSenderSettings, 1)
    return payload_hash(
        {
            column.name: getattr(sender, column.name) if sender else None
            for column in FormSenderSettings.__table__.columns
            if column.name not in {"created_at", "updated_at", "updated_by_user_id"}
        }
    )


def valid_fixture_plan(item):
    try:
        body = Proposal.model_validate(
            {
                key: value
                for key, value in item.payload_snapshot.items()
                if key in Proposal.model_fields
            }
        )
        plan = body.execution_plan
        return bool(
            plan
            and body.delivery_method == "form_plan_fixture"
            and plan.project_id == item.project_id
            and plan.company_id == item.company_id
            and plan.payload_version == item.payload_version
            and plan_hash(plan) == item.payload_snapshot.get("execution_plan_hash")
        )
    except (ValidationError, ValueError, TypeError):
        return False


def valid_adapter_plan(item):
    try:
        proposal = Proposal.model_validate(
            {k: v for k, v in item.payload_snapshot.items() if k in Proposal.model_fields}
        )
        plan = proposal.adapter_plan
        if not plan or proposal.delivery_method != "form_adapter":
            return False
        core = adapter_snapshot(plan)
        return (
            all(item.payload_snapshot.get(k) == v for k, v in core.items())
            and plan.project_id == item.project_id
            and plan.company_id == item.company_id
            and plan.source_draft_id == item.source_draft_id
            and plan.payload_version == item.payload_version
        )
    except (ValidationError, ValueError, TypeError):
        return False


def invalidate_if_needed(db, item):
    if item.status not in {"PENDING", "APPROVED"}:
        return
    reason = None
    status = "REVOKED"
    if item.expires_at <= now():
        reason, status = "request expired", "EXPIRED"
    elif payload_hash(item.payload_snapshot) != item.payload_hash:
        reason = "payload integrity mismatch"
    elif item.delivery_method == "form_plan_fixture" and not valid_fixture_plan(item):
        reason = "fixture execution plan binding mismatch"
    elif item.delivery_method == "form_adapter" and not valid_adapter_plan(item):
        reason = "adapter execution plan binding mismatch"
    elif company_fingerprint(db.get(Company, item.company_id)) != item.payload_snapshot.get(
        "company_source_hash"
    ):
        reason = "company target changed"
    elif item.channel == "form" and form_dependency_hash(
        db, item.company_id
    ) != item.payload_snapshot.get("form_profile_hash"):
        reason = "form profile or mapping changed"
    elif (
        item.channel == "form"
        and "sender_source_hash" in item.payload_snapshot
        and (form_sender_hash(db) != item.payload_snapshot["sender_source_hash"])
    ):
        reason = "form sender settings changed"
    elif item.source_draft_id:
        draft = db.get(OutreachDraft, item.source_draft_id)
        if not draft or draft_fingerprint(draft) != item.payload_snapshot["source_draft_hash"]:
            reason = "source draft changed"
    if reason:
        before = item.status
        item.status, item.invalidation_reason = status, reason
        audit(
            db,
            item,
            "expired" if status == "EXPIRED" else "revoked",
            "SYSTEM",
            None,
            before,
            reason,
        )


def expected(item, body: ExpectedPayload):
    if body.expected_hash != item.payload_hash or body.expected_version != item.payload_version:
        raise HTTPException(409, "提案内容が更新されています。再取得してください。")


def active_pending(db, item, body):
    expected(item, body)
    invalidate_if_needed(db, item)
    if item.status != "PENDING":
        db.commit()  # Keep expiry/invalidation together with its ledger entry.
        raise HTTPException(409, "この提案は承認待ちではありません。")


def create_proposal(
    db: Session,
    project_id: UUID,
    body: Proposal,
    principal_type: str,
    actor_id: UUID,
    previous=None,
    commit=True,
    allow_adapter_preparation=False,
):
    if body.delivery_method == "form_adapter":
        if not allow_adapter_preparation or principal_type != "HUMAN" or previous:
            raise HTTPException(409, "管理下フォームは専用の保存済み準備から作成してください。")
        from app.services.form_adapter_preparation import adapter_preparation
    company = db.get(Company, body.company_id)
    if not company or company.project_id != project_id:
        raise HTTPException(404, "企業が見つかりません。")
    draft = db.get(OutreachDraft, body.source_draft_id) if body.source_draft_id else None
    if body.source_draft_id and (
        not draft
        or draft.company_id != company.id
        or draft.channel != body.channel
        or draft.subject != body.subject
        or draft.body != body.body
    ):
        raise HTTPException(409, "Draftと提案内容が一致しません。")
    if body.adapter_plan:
        prepared, _ = adapter_preparation(db, company, draft)
        if prepared.model_dump(mode="json") != body.model_dump(mode="json"):
            raise HTTPException(409, "保存済み計画と提案が一致しません。")
    proposal_id = previous.proposal_id if previous else uuid4()
    version = previous.payload_version + 1 if previous else 1
    if body.execution_plan and (
        body.execution_plan.project_id != project_id
        or body.execution_plan.payload_version != version
    ):
        raise HTTPException(409, "操作計画のProjectまたはversionが一致しません。")
    snapshot = body.model_dump(
        mode="json", exclude={"expires_in_hours", "expected_hash", "expected_version"}
    )
    if body.execution_plan:
        snapshot["execution_plan_hash"] = plan_hash(body.execution_plan)
    else:
        snapshot.pop("execution_plan", None)  # Preserve legacy canonical payload shape.
    if body.adapter_plan:
        snapshot["adapter_plan"] = canonical_plan(body.adapter_plan)
        snapshot["adapter_plan_hash"] = adapter_plan_hash(body.adapter_plan)
    else:
        snapshot.pop("adapter_plan", None)
    snapshot.update(
        project_id=str(project_id),
        proposal_id=str(proposal_id),
        payload_version=version,
        canonicalization_version="json-v1",
        source_draft_hash=draft_fingerprint(draft) if draft else None,
        company_source_hash=company_fingerprint(company),
        form_profile_hash=form_dependency_hash(db, company.id) if body.channel == "form" else None,
    )
    if body.channel == "form":
        snapshot["sender_source_hash"] = form_sender_hash(db)
    created_at = now()
    item = ApprovalRequest(
        id=uuid4(),
        project_id=project_id,
        company_id=company.id,
        channel=body.channel,
        delivery_method=body.delivery_method,
        source_draft_id=body.source_draft_id,
        recipient=body.recipient,
        form_url=str(body.form_url) if body.form_url else None,
        subject=body.subject,
        body=body.body,
        sender=body.sender.model_dump(mode="json"),
        field_values=body.field_values,
        payload_snapshot=snapshot,
        payload_hash=payload_hash(snapshot),
        payload_version=version,
        canonicalization_version="json-v1",
        proposal_id=proposal_id,
        supersedes_request_id=previous.id if previous else None,
        created_by_principal_type=principal_type,
        created_by_user_id=actor_id if principal_type == "HUMAN" else None,
        created_by_agent_id=actor_id if principal_type == "AGENT" else None,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=body.expires_in_hours),
        status="PENDING",
    )
    if previous:
        if previous.status not in {"PENDING", "APPROVED"}:
            raise HTTPException(409, "この提案から改訂できません。")
        before = previous.status
        previous.status, previous.invalidation_reason = "REVOKED", "superseded by revision"
        audit(db, previous, "revoked", principal_type, actor_id, before, "superseded by revision")
    db.add(item)
    db.flush()
    audit(
        db, item, "revision created" if previous else "proposal created", principal_type, actor_id
    )
    if commit:
        db.commit()
    return item


def challenge(db, item, body, user, session_hash):
    active_pending(db, item, body)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    recent = db.scalar(
        select(func.count())
        .select_from(HumanApprovalProof)
        .where(
            HumanApprovalProof.user_id == user.id,
            HumanApprovalProof.expires_at > now(),
        )
    )
    if recent >= 5:
        raise HTTPException(429, "再認証の回数が多すぎます。5分後に再試行してください。")
    token = secrets.token_urlsafe(32)
    proof = HumanApprovalProof(
        request_id=item.id,
        user_id=user.id,
        session_hash=session_hash,
        payload_hash=item.payload_hash,
        payload_version=item.payload_version,
        action="APPROVE",
        token_hash=token_digest(token),
        expires_at=now() + timedelta(minutes=5),
    )
    db.add(proof)
    db.commit()
    return {"challenge_token": token, "expires_at": proof.expires_at, "method": proof.method}


def bound_proof(db, item, token, user, session_hash):
    proof = db.scalar(
        select(HumanApprovalProof)
        .where(HumanApprovalProof.token_hash == token_digest(token))
        .with_for_update()
    )
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == session_hash).with_for_update()
    )
    if (
        not proof
        or proof.request_id != item.id
        or proof.user_id != user.id
        or proof.session_hash != session_hash
        or proof.action != "APPROVE"
        or proof.payload_hash != item.payload_hash
        or proof.payload_version != item.payload_version
        or proof.expires_at <= now()
        or proof.used_at
        or not session
        or session.user_id != user.id
        or session.expires_at <= now()
    ):
        audit(
            db,
            item,
            "authentication denied",
            "HUMAN",
            user.id,
            item.status,
            "invalid step-up proof",
        )
        db.commit()
        raise HTTPException(403, "再認証が無効です。もう一度確認してください。")
    return proof


class PasswordStepUpVerifier:
    """Replaceable reauthentication boundary; no session-to-Agent conversion."""

    method = "password-v1"

    def verify(self, user: User, password: str) -> bool:
        return password_hasher.verify(password, user.password_hash)


step_up_verifier = PasswordStepUpVerifier()


def verify_challenge(db, item, body, user, session_hash):
    invalidate_if_needed(db, item)
    proof = bound_proof(db, item, body.challenge_token, user, session_hash)
    if item.status != "PENDING" or proof.verified_at:
        raise HTTPException(409, "再認証challengeを再利用できません。")
    if not step_up_verifier.verify(user, body.password):
        proof.used_at = now()  # A failed attempt also burns the challenge.
        audit(db, item, "authentication denied", "HUMAN", user.id, item.status, "step-up failed")
        db.commit()
        raise HTTPException(403, "再認証に失敗しました。")
    proof.verified_at = now()
    db.commit()
    return {"verified": True}


def approve(db, item, body, user, session_hash):
    if not isinstance(user, User):
        raise HTTPException(403, "Human承認が必要です。")
    active_pending(db, item, body)
    proof = bound_proof(db, item, body.challenge_token, user, session_hash)
    if not proof.verified_at:
        audit(db, item, "authentication denied", "HUMAN", user.id, item.status, "step-up required")
        db.commit()
        raise HTTPException(403, "再認証が必要です。")
    proof.used_at = now()
    item.status = "APPROVED"
    item.approved_by_user_id, item.approved_at = user.id, now()
    item.approved_payload_hash, item.approved_payload_version = (
        item.payload_hash,
        item.payload_version,
    )
    audit(db, item, "approval granted", "HUMAN", user.id, "PENDING")
    db.commit()
    return item


def decide(db, item, body, user, action):
    expected(item, body)
    invalidate_if_needed(db, item)
    allowed = {"PENDING"} if action == "REJECTED" else {"PENDING", "APPROVED"}
    if item.status not in allowed:
        db.commit()
        raise HTTPException(409, "この状態から変更できません。")
    before, item.status = item.status, action
    if action == "REJECTED":
        item.rejection_reason = body.reason
    else:
        item.invalidation_reason = body.reason
    audit(
        db,
        item,
        "rejected" if action == "REJECTED" else "revoked",
        "HUMAN",
        user.id,
        before,
        "human decision",
    )
    db.commit()
    return item


def valid_approved_payload(db, item) -> bool:
    """A3 may reuse this check; deliberately does not consume or dispatch."""
    invalidate_if_needed(db, item)
    return (
        item.status == "APPROVED"
        and item.approved_payload_hash == item.payload_hash
        and item.approved_payload_version == item.payload_version
        and payload_hash(item.payload_snapshot) == item.payload_hash
    )
