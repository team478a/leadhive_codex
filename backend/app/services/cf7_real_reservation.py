"""Separate Human reapproval and reservation contract. No transport or worker registration."""

from copy import deepcopy
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalRequest, Company, HumanApprovalProof, OutreachDraft, User
from app.project_access import project_access
from app.services import human_approval as approval
from app.services.cf7_real_approval import METHOD as CANDIDATE_METHOD

METHOD = "cf7_real_reservation"


def human_proof(db: Session, item: ApprovalRequest) -> bool:
    return (
        db.scalar(
            select(HumanApprovalProof.id)
            .where(
                HumanApprovalProof.request_id == item.id,
                HumanApprovalProof.user_id == item.approved_by_user_id,
                HumanApprovalProof.payload_hash == item.payload_hash,
                HumanApprovalProof.payload_version == item.payload_version,
                HumanApprovalProof.verified_at.is_not(None),
                HumanApprovalProof.used_at.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def plan(db: Session, source: ApprovalRequest) -> dict:
    if source.delivery_method != CANDIDATE_METHOD or not approval.valid_approved_payload(
        db, source
    ):
        raise HTTPException(409, "有効な実サイト候補のHuman承認が必要です。")
    if source.approved_at is None or not human_proof(db, source):
        raise HTTPException(409, "候補内容のHuman再認証証明を確認できません。")
    user = db.get(User, source.approved_by_user_id)
    if not user:
        raise HTTPException(409, "候補承認者が無効です。")
    project_access(source.project_id, db, user)
    packet = source.payload_snapshot["cf7_real_handoff"]
    return {
        "definition_version": "cf7-real-reservation-plan-v1",
        "environment": "RESERVATION_ONLY",
        "source_approval_id": str(source.id),
        "source_approval_hash": source.payload_hash,
        "source_approval_version": source.payload_version,
        "source_approved_by": str(source.approved_by_user_id),
        "source_approved_at": source.approved_at.isoformat(),
        "input_packet": deepcopy(packet),
        "expires_at": min(
            source.expires_at, datetime.fromisoformat(packet["snapshot"]["expires_at"])
        ).isoformat(),
        "constraints": {
            "fresh_observation_required": True,
            "permission_allowed_before_execution": True,
            "duplicate_check_required": True,
            "rate_limit_required": True,
            "unknown_auto_retry": False,
            "executable_contract_requires_new_human_approval": True,
        },
        "execution_allowed": False,
    }


def preview(db: Session, source: ApprovalRequest) -> dict:
    prepared = plan(db, source)
    return {
        "plan": prepared,
        "preparation_hash": approval.payload_hash(prepared),
        "reservation_only": True,
        "execution_enabled": False,
    }


def envelope(source: ApprovalRequest, prepared: dict, proposal_id: UUID) -> dict:
    outer = deepcopy(source.payload_snapshot)
    outer.pop("cf7_real_handoff")
    outer.update(
        delivery_method=METHOD,
        proposal_id=str(proposal_id),
        payload_version=1,
        cf7_reservation_plan=prepared,
        cf7_reservation_plan_hash=approval.payload_hash(prepared),
    )
    return outer


def create_request(
    db: Session, source: ApprovalRequest, user: User, expected_hash: str
) -> ApprovalRequest:
    prepared = plan(db, source)
    digest = approval.payload_hash(prepared)
    if digest != expected_hash:
        raise HTTPException(
            409, "候補・入力・証拠が変更されています。準備内容を読み直してください。"
        )
    existing = db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.company_id == source.company_id,
            ApprovalRequest.delivery_method == METHOD,
            ApprovalRequest.created_by_user_id == user.id,
            ApprovalRequest.status.in_(("PENDING", "APPROVED")),
            ApprovalRequest.payload_snapshot["cf7_reservation_plan_hash"].astext == digest,
        )
        .order_by(ApprovalRequest.created_at.desc())
        .with_for_update()
    )
    if existing:
        approval.invalidate_if_needed(db, existing)
        if existing.status in {"PENDING", "APPROVED"}:
            db.commit()
            return existing
    proposal_id = uuid4()
    outer = envelope(source, prepared, proposal_id)
    if datetime.fromisoformat(prepared["expires_at"]) <= approval.now():
        raise HTTPException(409, "候補の証拠期限が切れました。")
    item = ApprovalRequest(
        project_id=source.project_id,
        company_id=source.company_id,
        channel="form",
        delivery_method=METHOD,
        source_draft_id=source.source_draft_id,
        form_url=source.form_url,
        subject=source.subject,
        body=source.body,
        sender=deepcopy(source.sender),
        field_values=deepcopy(source.field_values),
        payload_snapshot=outer,
        payload_hash=approval.payload_hash(outer),
        payload_version=1,
        canonicalization_version="json-v1",
        proposal_id=proposal_id,
        created_by_principal_type="HUMAN",
        created_by_user_id=user.id,
        created_at=approval.now(),
        expires_at=datetime.fromisoformat(prepared["expires_at"]),
        status="PENDING",
    )
    db.add(item)
    db.flush()
    approval.audit(
        db, item, "proposal created", "HUMAN", user.id, reason="CF7 reservation reapproval required"
    )
    db.commit()
    return item


def valid_request(db: Session, item: ApprovalRequest) -> bool:
    try:
        saved = item.payload_snapshot["cf7_reservation_plan"]
        source = db.get(ApprovalRequest, UUID(saved["source_approval_id"]))
        if not source or source.id == item.id or source.delivery_method != CANDIDATE_METHOD:
            return False
        prepared = plan(db, source)
        outer = envelope(source, prepared, item.proposal_id)
        return (
            item.channel == "form"
            and item.delivery_method == METHOD
            and item.recipient is None
            and item.payload_version == 1
            and item.canonicalization_version == "json-v1"
            and item.created_by_principal_type == "HUMAN"
            and item.created_by_user_id is not None
            and item.created_by_agent_id is None
            and item.project_id == source.project_id
            and item.company_id == source.company_id
            and item.source_draft_id == source.source_draft_id
            and item.payload_snapshot == outer
            and item.expires_at <= source.expires_at
            and all(
                getattr(item, k) == getattr(source, k)
                for k in ("form_url", "subject", "body", "sender", "field_values")
            )
        )
    except (HTTPException, KeyError, ValueError, TypeError):
        return False


def validate_reservation(db: Session, item: ApprovalRequest) -> tuple[Company, OutreachDraft]:
    if (
        item.delivery_method != METHOD
        or not approval.valid_approved_payload(db, item)
        or not human_proof(db, item)
    ):
        raise HTTPException(409, "予約用のHuman再承認が必要です。候補承認だけでは予約できません。")
    approver = db.get(User, item.approved_by_user_id)
    if not approver:
        raise HTTPException(409, "予約承認者が無効です。")
    project_access(item.project_id, db, approver)
    company = db.get(Company, item.company_id)
    draft = db.get(OutreachDraft, item.source_draft_id)
    if not company or not draft or draft.company_id != company.id:
        raise HTTPException(409, "承認した企業・Draftが無効です。")
    return company, draft
