"""Commit approval consumption and UNKNOWN evidence before any form POST."""

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models import (
    Activity,
    ApprovalRequest,
    ApprovedFormDispatch,
    Company,
    FormDelivery,
    OutreachDraftApproval,
    User,
)
from app.project_access import project_access
from app.services import approved_form as service
from app.services import form_site_rate
from app.services import human_approval as approval
from app.services.form_delivery import FormDeliveryError, submit_form
from app.services.form_profile_delivery import inspect_delivery_profile
from app.services.form_submission_guard import UNKNOWN_MESSAGE, reserve_form_submission


def block(db, row_id, worker_id, reason):
    db.rollback()
    row = db.scalar(
        select(ApprovedFormDispatch).where(ApprovedFormDispatch.id == row_id).with_for_update()
    )
    if row.status != "checking" or row.worker_id != worker_id:
        return
    item = db.get(ApprovalRequest, row.approval_id)
    row.status, row.reason, row.finished_at = "blocked", reason[:500], approval.now()
    if item.delivery_method == "form_adapter":
        row.worker_id = None
    approval.invalidate_if_needed(db, item)
    approval.audit(db, item, "form dispatch blocked", "SYSTEM", None, item.status, reason[:500])
    db.commit()


def begin(db, row_id, worker_id, context, *, adapter_plan=None):
    db.expire_all()
    service.lock(db)
    row = db.scalar(
        select(ApprovedFormDispatch).where(ApprovedFormDispatch.id == row_id).with_for_update()
    )
    if row.status != "checking" or row.worker_id != worker_id:
        db.commit()
        return None
    if not settings.outbound_enabled or not settings.human_approved_form_enabled:
        raise HTTPException(409, "フォーム実行設定が停止されています。")
    if row.lease_expires_at <= approval.now() or not service.capacity(db):
        raise HTTPException(409, "実行期限または送信上限により停止しました。")
    if not form_site_rate.eligible(db, row):
        raise HTTPException(409, "同じサイトへの試行間隔により停止しました。")
    item = db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.id == row.approval_id).with_for_update()
    )
    if adapter_plan is not None:
        from app.services.controlled_form_execution import validate_context

        validate_context(db, item, row, context, adapter_plan)
    if (
        row.payload_hash != item.payload_hash
        or row.payload_snapshot != item.payload_snapshot
        or approval.payload_hash(row.payload_snapshot) != row.payload_hash
    ):
        raise HTTPException(409, "固定payloadの整合性を確認できません。")
    try:
        company, draft = service.validate(db, item, allow_adapter=adapter_plan is not None)
    except HTTPException:
        db.commit()  # Retain invalidation ledger, then block this reservation separately.
        raise
    creator = db.get(User, row.created_by_user_id)
    if not creator:
        raise HTTPException(409, "予約者が無効です。")
    project_access(row.project_id, db, creator)
    if service.duplicate(db, row.company_id, row.form_url, row.id):
        raise HTTPException(409, "宛先に既存の送信・結果不明の記録があります。")
    if (
        context.preview.form_url != row.form_url
        or context.preview.action_url != row.payload_snapshot["form_action_url"]
    ):
        raise HTTPException(409, "フォームURLまたはPOST先が承認時から変更されています。")
    authorization = None
    if adapter_plan is not None:
        authorization = {
            "approval_id": str(item.id),
            "payload_hash": item.payload_hash,
            "payload_version": item.payload_version,
            "adapter_plan_hash": item.payload_snapshot["adapter_plan_hash"],
        }
    delivery = reserve_form_submission(
        db,
        company,
        draft,
        context,
        item.approved_by_user_id,
        commit=False,
        delivery_method="adapter" if adapter_plan is not None else "direct",
        execution_authorization=authorization,
    )
    row.delivery_id, row.started_at, row.status = delivery.id, approval.now(), "unknown"
    row.reason = UNKNOWN_MESSAGE
    db.flush()  # Durable evidence must exist before the approval transition trigger.
    item.status = "CONSUMED"
    approval.audit(db, item, "form dispatch started", "SYSTEM", None, "APPROVED")
    db.commit()
    return row


def run(db, claimed):
    row_id, worker_id = claimed.id, claimed.worker_id
    if not settings.outbound_enabled or not settings.human_approved_form_enabled:
        block(db, row_id, worker_id, "フォーム実行設定が停止されています。")
        return
    try:
        item = db.get(ApprovalRequest, claimed.approval_id)
        company, draft = service.validate(db, item)
        db.commit()
        context = inspect_delivery_profile(db, company, draft)  # GET only; no locks across I/O.
        row = begin(db, row_id, worker_id, context)
        if row is None:
            return
    except (HTTPException, FormDeliveryError) as exc:
        reason = str(exc.detail) if isinstance(exc, HTTPException) else exc.public_message
        block(db, row_id, worker_id, reason)
        return
    except Exception:
        block(db, row_id, worker_id, "フォームの事前確認に失敗しました。再承認してください。")
        return
    result, message, submission = "unknown", UNKNOWN_MESSAGE, None
    try:
        _, submission = submit_form(
            row.form_url,
            row.payload_snapshot["field_values"],
            form_index=context.profile.form_index,
            profile_fields=context.fields,
            form_profile_id=context.profile.id,
            expected_fingerprint=context.profile.fingerprint,
            expected_action_url=row.payload_snapshot["form_action_url"],
            confirmation_expected=False,  # Only a known single-stage form is authorized here.
        )
        result, message = "submitted", ""
    except FormDeliveryError as exc:
        if not exc.submission_unknown:
            result, message = "failed", exc.public_message
    except Exception:
        pass  # Unknown acceptance must never return to a retryable queue.
    finish(db, row_id, worker_id, result, message, submission)


def finish(db, row_id, worker_id, result, message, submission):
    if result not in {"unknown", "submitted", "failed"}:
        raise ValueError("Invalid form result")
    db.rollback()
    row = db.scalar(
        select(ApprovedFormDispatch).where(ApprovedFormDispatch.id == row_id).with_for_update()
    )
    if row.status != "unknown" or row.worker_id != worker_id:
        return
    delivery = db.get(FormDelivery, row.delivery_id)
    row.status, row.reason, row.finished_at = result, message, approval.now()
    delivery.status, delivery.error_message = result, message
    if submission:
        delivery.submitted_at = approval.now()
        delivery.response_status = submission.response_status
        delivery.final_url = submission.final_url
        delivery.confirmation_used = submission.confirmation_used
        delivery.completion_evidence = submission.completion_evidence
    item = db.get(ApprovalRequest, row.approval_id)
    approval.audit(
        db, item, f"form dispatch {result}", "SYSTEM", None, item.status, message or None
    )
    if submission:
        db.add(
            OutreachDraftApproval(
                draft_id=row.draft_id,
                approved_by_user_id=item.approved_by_user_id,
                approval_type="form_adapter"
                if item.delivery_method == "form_adapter"
                else "form_direct",
                subject=row.payload_snapshot["subject"],
                body=row.payload_snapshot["body"],
                approved_at=item.approved_at,
                delivered_at=delivery.submitted_at,
            )
        )
        company = db.get(Company, row.company_id)
        if company.status in {"unreviewed", "target"}:
            company.status = "approached"
            db.add(
                Activity(
                    company_id=company.id,
                    activity_type="status_change",
                    note="営業状況を更新: アプローチ済（Human承認済みフォーム）",
                )
            )
    db.add(
        Activity(
            company_id=row.company_id,
            activity_type="form",
            note=f"承認済みフォーム実行結果: {result}",
        )
    )
    db.commit()
