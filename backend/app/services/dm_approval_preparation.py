"""Stored evidence to PENDING only. No reservation, network or delivery calls."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.config import settings
from app.models import (
    ApprovalRequest,
    Company,
    LeadDmPreparation,
    OutreachDraft,
    Project,
    SmtpSettings,
)
from app.schema_approval import Proposal, Sender
from app.services import dm_preparation, human_approval
from app.services.contact_destinations import normalize_destination
from app.services.form_approval_preparation import preparation as form_preparation
from app.services.form_profile_delivery import primary_form_profile

BINDING = "lead_dm_binding"


def bound_draft(db, draft_id):
    return (
        db.scalar(
            select(ApprovalRequest.id)
            .where(
                ApprovalRequest.source_draft_id == draft_id,
                ApprovalRequest.payload_snapshot.has_key(BINDING),
            )
            .limit(1)
        )
        is not None
    )


def latest_preparation(db, company_id):
    return db.scalar(
        select(LeadDmPreparation)
        .where(LeadDmPreparation.company_id == company_id)
        .order_by(LeadDmPreparation.created_at.desc(), LeadDmPreparation.id.desc())
        .limit(1)
    )


def proposal_and_binding(db, row, company, project):
    current = latest_preparation(db, company.id)
    if current is None or current.id != row.id:
        raise HTTPException(409, "新しい根拠付き下書きがあります。最新の下書きを確認してください。")
    prepared = dm_preparation.public(db, company, project, row)
    if prepared["status"] != "DRAFT_PREPARED":
        messages = {
            "PREPARATION_EXPIRED": "根拠付き下書きの期限が切れています。再準備してください。",
            "DESTINATION_CHOICE_CHANGED": (
                "窓口選択・用途・連絡可否が無効です。窓口の診断理由を確認してください。"
            ),
            "DESTINATION_CHANGED": "宛先情報が変わりました。最新の窓口で再準備してください。",
            "SALES_CONTEXT_CHANGED": "営業条件が変わりました。下書きを再準備してください。",
            "TEMPLATE_CHANGED": "テンプレートが変更・削除されました。再準備してください。",
        }
        raise HTTPException(
            409, messages.get(prepared["reason"], "根拠付き下書きを再確認してください。")
        )
    stored = row.snapshot
    destination = stored["destination"]
    if destination["type"] == "email":
        config = db.get(SmtpSettings, 1)
        sender = Sender(
            name=(config.from_name if config else settings.smtp_from_name).strip(),
            email=(config.from_email if config else settings.smtp_from_email).strip(),
        )
        proposal = Proposal(
            company_id=company.id,
            channel="email",
            delivery_method="email",
            recipient=destination["destination"],
            subject=stored["subject"],
            body=stored["body"],
            sender=sender,
        )
        sender_hash = human_approval.payload_hash(sender.model_dump(mode="json"))
    else:
        profile = primary_form_profile(db, company.id)
        if not profile or profile.confirmation_page is not False:
            raise HTTPException(
                409, "確認画面・フォーム段階が未確定です。Humanによる確認が必要です。"
            )
        if normalize_destination("form", profile.form_url) != destination["destination"]:
            raise HTTPException(409, "選択した窓口と解析フォームが一致しません。")
        normalize_destination("form", profile.action_url)
        draft = SimpleNamespace(
            id=None,
            company_id=company.id,
            channel="form",
            subject=stored["subject"],
            body=stored["body"],
        )
        proposal, _ = form_preparation(db, company, draft)
        sender_hash = human_approval.form_sender_hash(db)
    binding = dict(
        version="lead-dm-c2-v1",
        preparation_id=str(row.id),
        source_snapshot_hash=human_approval.payload_hash(stored),
        choice_version=row.choice_version,
        sender_hash=sender_hash,
        evidence=stored["evidence"],
        expires_at=row.expires_at.isoformat(),
    )
    binding["preparation_hash"] = human_approval.payload_hash(
        dict(
            binding=binding,
            proposal=proposal.model_dump(
                mode="json", exclude={"source_draft_id", "expires_in_hours"}
            ),
            form_hash=human_approval.form_dependency_hash(db, company.id)
            if proposal.channel == "form"
            else None,
        )
    )
    return proposal, binding


def valid_request(db, item):
    try:
        if human_approval.payload_hash(item.payload_snapshot) != item.payload_hash:
            return False
        binding = item.payload_snapshot[BINDING]
        row = db.get(LeadDmPreparation, UUID(binding["preparation_id"]))
        company, project = db.get(Company, item.company_id), db.get(Project, item.project_id)
        if (
            not row
            or not company
            or not project
            or row.company_id != company.id
            or row.project_id != project.id
        ):
            return False
        proposal, expected_binding = proposal_and_binding(db, row, company, project)
        if expected_binding != binding:
            return False
        expected = proposal.model_dump(mode="json", exclude={"source_draft_id", "expires_in_hours"})
        if any(item.payload_snapshot.get(k) != v for k, v in expected.items()):
            return False
        draft = db.get(OutreachDraft, item.source_draft_id) if item.source_draft_id else None
        return bool(
            draft
            and draft.company_id == company.id
            and draft.channel == proposal.channel
            and draft.subject == proposal.subject
            and draft.body == proposal.body
            and human_approval.draft_fingerprint(draft)
            == item.payload_snapshot.get("source_draft_hash")
        )
    except (HTTPException, ValidationError, ValueError, KeyError, TypeError):
        return False


def current_request(db, row):
    return db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.company_id == row.company_id,
            ApprovalRequest.project_id == row.project_id,
            ApprovalRequest.payload_snapshot[BINDING]["preparation_id"].astext == str(row.id),
        )
        .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
        .limit(1)
    )


def preview(db, row, company, project):
    try:
        proposal, binding = proposal_and_binding(db, row, company, project)
    except (HTTPException, ValidationError, ValueError) as exc:
        message = (
            exc.detail
            if isinstance(exc, HTTPException)
            else "送信者名・メールアドレス・フォーム入力値を確認してください。"
        )
        return dict(
            status="HOLD",
            reason=message,
            preparation_hash=None,
            proposal=None,
            dm_ready=False,
            execution_allowed=False,
            approval_request=None,
        )
    item = current_request(db, row)
    active = bool(
        item
        and item.status in {"PENDING", "APPROVED"}
        and item.expires_at > datetime.now(timezone.utc)
        and valid_request(db, item)
    )
    return dict(
        status="DM_READY" if active else "READY_TO_PREPARE",
        reason=None,
        preparation_hash=binding["preparation_hash"],
        proposal=proposal.model_dump(mode="json"),
        evidence=binding["evidence"],
        dm_ready=active,
        execution_allowed=False,
        approval_request=dict(
            id=item.id,
            status=item.status,
            payload_hash=item.payload_hash,
            payload_version=item.payload_version,
            expires_at=item.expires_at,
            valid=active,
        )
        if item
        else None,
    )


def create(db, row, company, project, user, expected_hash):
    try:
        proposal, binding = proposal_and_binding(db, row, company, project)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(409, "送信者・フォーム入力値を確認してください。") from exc
    if binding["preparation_hash"] != expected_hash:
        raise HTTPException(409, "送信者・下書き・入力値が変わりました。再確認してください。")
    previous = current_request(db, row)
    if previous and previous.status in {"PENDING", "APPROVED"}:
        human_approval.invalidate_if_needed(db, previous)
        if previous.status in {"PENDING", "APPROVED"}:
            return previous  # Repeated preparation cannot multiply active proposals.
    draft = OutreachDraft(
        company_id=company.id,
        created_by_user_id=user.id,
        channel=proposal.channel,
        subject=proposal.subject,
        body=proposal.body,
        ai_provider="template-evidence",
        ai_model="human-observed-v1",
    )
    db.add(draft)
    db.flush()
    proposal = proposal.model_copy(update={"source_draft_id": draft.id})
    item = human_approval.create_proposal(
        db,
        project.id,
        proposal,
        "HUMAN",
        user.id,
        commit=False,
        lead_dm_binding=binding,
        expiry_cap=row.expires_at,
    )
    db.commit()
    return item


def readiness(db, company, project):
    row = latest_preparation(db, company.id)
    if row is None:
        return dict(dm_ready=False, reason="根拠付き下書きが未作成です。")
    result = preview(db, row, company, project)
    return dict(
        dm_ready=result["dm_ready"],
        reason=result["reason"]
        or (None if result["dm_ready"] else "送信者・入力値を固定した承認待ち提案が必要です。"),
    )
