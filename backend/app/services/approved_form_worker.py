"""Commit approval consumption and UNKNOWN evidence before any form POST."""

import json
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models import (
    Activity,
    ApprovalRequest,
    ApprovedFormDispatch,
    BrowserFormRun,
    Company,
    FormDelivery,
    FormProfile,
    FormProfileField,
    OutreachDraft,
    OutreachDraftApproval,
    User,
)
from app.project_access import project_access
from app.services import approved_form as service
from app.services import form_site_rate
from app.services import human_approval as approval
from app.services.browser_form_plan import BrowserFormPlan, canonical_plan, plan_hash
from app.services.browser_form_runs import store_screenshot
from app.services.form_delivery import FormDeliveryError, submit_form
from app.services.form_profile_delivery import inspect_delivery_profile
from app.services.form_submission_guard import UNKNOWN_MESSAGE, reserve_form_submission


def _browser_context(db, plan_data):
    plan = BrowserFormPlan.model_validate_json(json.dumps(plan_data))
    profile = db.get(FormProfile, plan.form_profile_id)
    if profile is None or profile.fingerprint != plan.form_fingerprint:
        raise HTTPException(409, "承認時のフォーム解析と一致しません。")
    fields = db.scalars(
        select(FormProfileField)
        .where(FormProfileField.form_profile_id == profile.id)
        .order_by(FormProfileField.position, FormProfileField.id)
    ).all()
    planned_ids = {field.profile_field_id for field in plan.fields}
    if not planned_ids.issubset({field.id for field in fields}):
        raise HTTPException(409, "承認時のフォーム項目と一致しません。")
    return plan, SimpleNamespace(
        profile=profile,
        fields=fields,
        preview=SimpleNamespace(form_url=plan.form_url, action_url=plan.action_url),
        values={field.name: field.value for field in plan.fields},
    )


def block(db, row_id, worker_id, reason):
    db.rollback()
    row = db.scalar(
        select(ApprovedFormDispatch).where(ApprovedFormDispatch.id == row_id).with_for_update()
    )
    if row.status != "checking" or row.worker_id != worker_id:
        return
    item = db.get(ApprovalRequest, row.approval_id)
    row.status, row.reason, row.finished_at = "blocked", reason[:500], approval.now()
    if item.delivery_method == "browser_form":
        run = db.scalar(select(BrowserFormRun).where(BrowserFormRun.dispatch_id == row.id))
        if run and run.status in {"checking", "queued"}:
            run.status, run.reason, run.finished_at = "blocked", reason[:500], approval.now()
            run.lease_expires_at = None
            run.payload_snapshot = {"mode": run.mode}
    if item.delivery_method == "form_adapter":
        row.worker_id = None
    approval.invalidate_if_needed(db, item)
    approval.audit(db, item, "form dispatch blocked", "SYSTEM", None, item.status, reason[:500])
    db.commit()


def begin(
    db,
    row_id,
    worker_id,
    context,
    *,
    adapter_plan=None,
    browser_form=False,
    dry_run=False,
    screenshot_before=None,
):
    if dry_run:
        if not settings.browser_form_delivery_enabled:
            raise HTTPException(409, "ブラウザーフォーム実行は停止されています。")
        run = db.scalar(
            select(BrowserFormRun).where(BrowserFormRun.id == row_id).with_for_update()
        )
        if (
            run is None
            or run.mode != "dry_run"
            or run.status != "checking"
            or run.worker_id != worker_id
            or run.lease_expires_at is None
            or run.lease_expires_at <= approval.now()
            or screenshot_before is None
        ):
            db.commit()
            return None
        plan, _ = _browser_context(db, run.payload_snapshot.get("browser_form_plan") or {})
        if (
            run.payload_hash != plan_hash(plan)
            or run.form_url != plan.form_url
            or run.form_fingerprint != plan.form_fingerprint
            or run.payload_snapshot.get("mode") != "dry_run"
        ):
            raise HTTPException(409, "dry-run計画の整合性を確認できません。")
        company = db.get(Company, run.company_id)
        draft = db.get(OutreachDraft, run.draft_id)
        from app.services.browser_form_preparation import preparation

        proposal, _preview = preparation(db, company, draft, allow_ai_suggestion=False)
        if (
            not proposal.browser_form_plan
            or canonical_plan(proposal.browser_form_plan) != canonical_plan(plan)
        ):
            raise HTTPException(409, "確認済みフォームまたは文面が変更されています。")
        store_screenshot(db, run.id, "before_submit", screenshot_before)
        run.started_at = approval.now()
        db.commit()
        return run

    db.expire_all()
    service.lock(db)
    row = db.scalar(
        select(ApprovedFormDispatch).where(ApprovedFormDispatch.id == row_id).with_for_update()
    )
    if row.status != "checking" or row.worker_id != worker_id:
        db.commit()
        return None
    from app.services.sending_window import allowed

    if not allowed(db):
        row.status, row.worker_id, row.lease_expires_at = "queued", None, None
        row.reason = "送信可能時間外のため待機中です。"
        if browser_form:
            run = db.scalar(
                select(BrowserFormRun)
                .where(BrowserFormRun.dispatch_id == row.id)
                .with_for_update()
            )
            if run:
                run.status, run.worker_id, run.lease_expires_at = "queued", None, None
                run.reason = row.reason
        db.commit()
        return None
    if not settings.outbound_enabled or not settings.human_approved_form_enabled:
        raise HTTPException(409, "フォーム実行設定が停止されています。")
    if browser_form and not settings.browser_form_delivery_enabled:
        raise HTTPException(409, "ブラウザーフォーム実行は停止されています。")
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
        company, draft = service.validate(
            db, item, allow_adapter=adapter_plan is not None or browser_form
        )
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
        delivery_method=(
            "adapter" if adapter_plan is not None else "browser" if browser_form else "direct"
        ),
        execution_authorization=authorization,
    )
    row.delivery_id, row.started_at, row.status = delivery.id, approval.now(), "unknown"
    row.reason = UNKNOWN_MESSAGE
    if browser_form:
        run = db.scalar(
            select(BrowserFormRun)
            .where(BrowserFormRun.dispatch_id == row.id)
            .with_for_update()
        )
        if (
            run is None
            or run.status != "checking"
            or run.worker_id != worker_id
            or screenshot_before is None
        ):
            raise HTTPException(409, "ブラウザー実行予約の状態を確認できません。")
        store_screenshot(db, run.id, "before_submit", screenshot_before)
        run.status, run.started_at = "unknown", approval.now()
        run.reason = UNKNOWN_MESSAGE
        run.payload_snapshot = {"mode": run.mode}
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


def run_browser_form(claimed):
    from app.database import SessionLocal
    from browser_worker.delivery import run_browser_delivery_task

    row_id, worker_id = claimed.id, claimed.worker_id
    started = False
    plan_data = claimed.payload_snapshot.get("browser_form_plan") or {}
    try:
        with SessionLocal() as session:
            item = session.get(ApprovalRequest, claimed.approval_id)
            service.validate(session, item, allow_adapter=True)
            plan, _ = _browser_context(session, plan_data)
            session.commit()

        def start_submission(screenshot):
            nonlocal started
            with SessionLocal() as session:
                _plan, context = _browser_context(session, plan_data)
                begun = begin(
                    session,
                    row_id,
                    worker_id,
                    context,
                    browser_form=True,
                    screenshot_before=screenshot,
                )
                started = begun is not None
                return started

        def cancelled():
            with SessionLocal() as session:
                current = session.get(ApprovedFormDispatch, row_id)
                return (
                    current is None
                    or current.worker_id != worker_id
                    or current.status not in {"checking", "unknown"}
                )

        result = run_browser_delivery_task(
            plan,
            mode="submit",
            before_post=start_submission,
            cancellation_check=cancelled,
        )
    except (HTTPException, FormDeliveryError) as exc:
        reason = str(exc.detail) if isinstance(exc, HTTPException) else exc.public_message
        with SessionLocal() as session:
            if started:
                finish(session, row_id, worker_id, "unknown", UNKNOWN_MESSAGE, None)
            else:
                block(session, row_id, worker_id, reason)
        return
    except Exception:
        with SessionLocal() as session:
            current = session.get(ApprovedFormDispatch, row_id)
            if started or current and current.status == "unknown":
                finish(session, row_id, worker_id, "unknown", UNKNOWN_MESSAGE, None)
            else:
                block(session, row_id, worker_id, "ブラウザーフォームの事前確認に失敗しました。")
        return
    with SessionLocal() as session:
        if result.status == "failed" and not started:
            block(session, row_id, worker_id, result.message or "POST前の安全確認に失敗しました。")
        else:
            finish(
                session,
                row_id,
                worker_id,
                result.status,
                result.message,
                SimpleNamespace(
                    response_status=result.response_status,
                    final_url=result.final_url,
                    confirmation_used=result.confirmation_used,
                    completion_evidence=result.completion_evidence,
                ),
                screenshot_after=result.screenshot_after,
            )


def run_browser_dry_run(claimed):
    from app.database import SessionLocal
    from browser_worker.delivery import run_browser_delivery_task

    run_id, worker_id = claimed.id, claimed.worker_id
    with SessionLocal() as session:
        run = session.get(BrowserFormRun, run_id)
        if run is None:
            return
        plan_data = run.payload_snapshot.get("browser_form_plan") or {}
        try:
            plan, _ = _browser_context(session, plan_data)
            company = session.get(Company, run.company_id)
            draft = session.get(OutreachDraft, run.draft_id)
            from app.services.browser_form_preparation import preparation

            proposal, _ = preparation(session, company, draft, allow_ai_suggestion=False)
            if (
                not proposal.browser_form_plan
                or canonical_plan(proposal.browser_form_plan) != canonical_plan(plan)
            ):
                raise HTTPException(409, "確認済みフォームまたは文面が変更されています。")
            session.commit()
        except Exception:
            session.rollback()
            finish(
                session,
                run_id,
                worker_id,
                "failed",
                "dry-runの事前確認に失敗しました。",
                None,
                dry_run=True,
            )
            return

    def start_dry_run(screenshot):
        with SessionLocal() as session:
            return begin(
                session, run_id, worker_id, None, dry_run=True, screenshot_before=screenshot
            ) is not None

    def cancelled():
        with SessionLocal() as session:
            current = session.get(BrowserFormRun, run_id)
            return current is None or current.worker_id != worker_id or current.status != "checking"

    try:
        result = run_browser_delivery_task(
            plan, mode="dry_run", before_post=start_dry_run, cancellation_check=cancelled
        )
    except Exception:
        with SessionLocal() as session:
            finish(
                session,
                run_id,
                worker_id,
                "failed",
                "dry-runを完了できませんでした。",
                None,
                dry_run=True,
            )
        return
    with SessionLocal() as session:
        finish(
            session,
            run_id,
            worker_id,
            result.status,
            result.message,
            None,
            screenshot_after=result.screenshot_after,
            dry_run=True,
        )


def finish(
    db,
    row_id,
    worker_id,
    result,
    message,
    submission,
    *,
    screenshot_after=None,
    dry_run=False,
):
    if dry_run:
        db.rollback()
        run = db.scalar(
            select(BrowserFormRun).where(BrowserFormRun.id == row_id).with_for_update()
        )
        if (
            run is None
            or run.mode != "dry_run"
            or run.status != "checking"
            or run.worker_id != worker_id
        ):
            return
        if result not in {"dry_run_completed", "failed", "blocked", "cancelled"}:
            raise ValueError("Invalid dry-run result")
        run.status = result
        run.reason = message[:500]
        run.payload_snapshot = {"mode": run.mode}
        run.finished_at = approval.now()
        run.lease_expires_at = None
        if screenshot_after:
            store_screenshot(db, run.id, "after_submit", screenshot_after)
        db.add(
            Activity(
                company_id=run.company_id,
                activity_type="form",
                note=f"ブラウザーdry-run結果: {run.status}",
            )
        )
        db.commit()
        return
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
        if result == "submitted":
            delivery.submitted_at = approval.now()
        delivery.response_status = submission.response_status
        delivery.final_url = submission.final_url
        delivery.confirmation_used = submission.confirmation_used
        delivery.completion_evidence = submission.completion_evidence
    item = db.get(ApprovalRequest, row.approval_id)
    if item.delivery_method == "browser_form":
        browser_run = db.scalar(
            select(BrowserFormRun)
            .where(BrowserFormRun.dispatch_id == row.id)
            .with_for_update()
        )
        if browser_run:
            browser_run.status, browser_run.reason = result, message[:500]
            browser_run.finished_at, browser_run.lease_expires_at = approval.now(), None
            browser_run.payload_snapshot = {"mode": browser_run.mode}
            if screenshot_after:
                store_screenshot(db, browser_run.id, "after_submit", screenshot_after)
    approval.audit(
        db, item, f"form dispatch {result}", "SYSTEM", None, item.status, message or None
    )
    if submission and result == "submitted":
        db.add(
            OutreachDraftApproval(
                draft_id=row.draft_id,
                approved_by_user_id=item.approved_by_user_id,
                approval_type={
                    "form_adapter": "form_adapter",
                    "browser_form": "browser_form",
                }.get(item.delivery_method, "form_direct"),
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
