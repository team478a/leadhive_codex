"""Stored-data operations and Human review. Never performs external I/O."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, or_, select

from app.models import (
    ApprovalRequest,
    ApprovedFormDispatch,
    Company,
    OutreachAuditEvent,
    OutreachDraft,
    User,
)
from app.services import human_approval as approval
from app.services.form_approval_preparation import preparation


def category():
    return case(
        (
            ApprovedFormDispatch.status.in_(("queued", "checking", "blocked"))
            & ApprovedFormDispatch.started_at.is_(None)
            & (ApprovalRequest.expires_at <= approval.now()),
            "expired",
        ),
        (
            (ApprovedFormDispatch.status == "checking")
            & (ApprovedFormDispatch.lease_expires_at <= approval.now()),
            "interrupted",
        ),
        else_=ApprovedFormDispatch.status,
    )


def reconcile_locked(db, project_id=None, limit=100):
    query = (
        select(ApprovedFormDispatch, ApprovalRequest)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovedFormDispatch.approval_id)
        .where(
            ApprovedFormDispatch.started_at.is_(None),
            or_(
                ApprovedFormDispatch.status.in_(("queued", "checking"))
                & (ApprovalRequest.expires_at <= approval.now()),
                (ApprovedFormDispatch.status == "checking")
                & (ApprovedFormDispatch.lease_expires_at <= approval.now()),
            ),
        )
    )
    if project_id:
        query = query.where(ApprovedFormDispatch.project_id == project_id)
    rows = db.execute(
        query.order_by(ApprovedFormDispatch.created_at, ApprovedFormDispatch.id)
        .limit(limit)
        .with_for_update()
    ).all()
    for row, item in rows:
        expired = item.expires_at <= approval.now()
        approval.invalidate_if_needed(db, item)
        row.status, row.finished_at, row.worker_id = "blocked", approval.now(), None
        row.reason = (
            "承認期限が切れました。内容を再確認し、再準備・再承認してください。"
            if expired
            else "事前確認が中断されました。再準備・再承認してください。"
        )
        approval.audit(
            db,
            item,
            "form reservation expired" if expired else "form preflight interrupted",
            "SYSTEM",
            None,
            item.status,
        )
    return len(rows)


def latest_reviews(db, request_ids):
    return {
        row.request_id: {
            "choice": row.reason,
            "actor_id": row.actor_id,
            "actor_label": email,
            "timestamp": row.timestamp,
        }
        for row, email in db.execute(
            select(OutreachAuditEvent, User.email)
            .outerjoin(User, User.id == OutreachAuditEvent.actor_id)
            .where(
                OutreachAuditEvent.request_id.in_(request_ids),
                OutreachAuditEvent.event == "form review recorded",
            )
            .distinct(OutreachAuditEvent.request_id)
            .order_by(
                OutreachAuditEvent.request_id,
                OutreachAuditEvent.timestamp.desc(),
                OutreachAuditEvent.id.desc(),
            )
        ).all()
    }


def reprepare_allowed(row, item):
    return (
        row.started_at is None
        and row.delivery_id is None
        and (
            row.status in {"blocked", "cancelled"}
            or (row.status == "queued" and item.expires_at <= approval.now())
        )
        and item.status != "CONSUMED"
    )


def source(db, row, item):
    if not reprepare_allowed(row, item):
        raise HTTPException(
            409, "未送信で停止した予約だけ再準備できます。結果不明・送信試行済みは再送できません。"
        )
    company, draft = db.get(Company, row.company_id), db.get(OutreachDraft, row.draft_id)
    if not company or not draft or draft.company_id != company.id:
        raise HTTPException(409, "企業または保存済みDraftを確認できません。")
    return company, draft


def existing_repreparation(db, item):
    event = db.scalar(
        select(OutreachAuditEvent)
        .where(
            OutreachAuditEvent.request_id == item.id,
            OutreachAuditEvent.event == "form repreparation linked",
        )
        .limit(1)
    )
    return db.get(ApprovalRequest, UUID(event.reason)) if event else None


def reprepare(db, row, item, body, user):
    approval.expected(item, body)
    source(db, row, item)
    existing = existing_repreparation(db, item)
    if existing:
        return existing  # The same stopped reservation never creates multiple proposals.
    from app.models import FormProfile, FormProfileField, FormSenderSettings

    company = db.scalar(
        select(Company)
        .where(Company.id == row.company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    draft = db.scalar(
        select(OutreachDraft)
        .where(OutreachDraft.id == row.draft_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    db.scalar(select(FormSenderSettings).where(FormSenderSettings.id == 1).with_for_update())
    db.scalars(
        select(FormProfile).where(FormProfile.company_id == company.id).with_for_update()
    ).all()
    db.scalars(
        select(FormProfileField)
        .where(
            FormProfileField.form_profile_id.in_(
                select(FormProfile.id).where(FormProfile.company_id == company.id)
            )
        )
        .with_for_update()
    ).all()
    proposal, preview = preparation(db, company, draft)
    if preview["preparation_hash"] != body.expected_preparation_hash:
        raise HTTPException(409, "準備内容が変更されています。もう一度内容を取得してください。")
    from app.services import approved_form

    if approved_form.duplicate(db, company.id, str(proposal.form_url), row.id):
        raise HTTPException(409, "別の予約・送信・結果不明があるため再準備できません。")
    if db.scalar(
        select(ApprovalRequest.id)
        .where(
            ApprovalRequest.company_id == company.id,
            ApprovalRequest.channel == "form",
            ApprovalRequest.id != item.id,
            ApprovalRequest.status.in_(("PENDING", "APPROVED")),
            ApprovalRequest.expires_at > approval.now(),
        )
        .limit(1)
    ):
        raise HTTPException(409, "既存の承認候補があります。承認キューを確認してください。")
    approval.invalidate_if_needed(db, item)
    if item.status in {"PENDING", "APPROVED"}:
        before = item.status
        item.status, item.invalidation_reason = "REVOKED", "reprepared stopped form reservation"
        approval.audit(db, item, "revoked", "HUMAN", user.id, before, item.invalidation_reason)
    if row.status == "queued":
        row.status, row.finished_at, row.reason = (
            "blocked",
            approval.now(),
            "期限切れ予約を再準備しました。",
        )
    new_item = approval.create_proposal(
        db, row.project_id, proposal, "HUMAN", user.id, commit=False
    )
    approval.audit(
        db, item, "form repreparation linked", "HUMAN", user.id, item.status, str(new_item.id)
    )
    db.commit()
    return new_item
