from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    Company,
    FormDelivery,
    FormDeliveryBatchItem,
    OutreachDraft,
    OutreachDraftApproval,
)
from app.services.contact_permission import evaluate_contact_permission
from app.services.form_delivery import FormDeliveryError, FormPreview, submit_form
from app.services.form_profile_delivery import (
    inspect_delivery_profile,
    mapping_snapshot,
    mark_profile_changed,
    required_missing,
)


def body_values(preview: FormPreview, body: str) -> tuple[dict[str, str], list[str]]:
    values = {field.name: field.value for field in preview.fields if field.value}
    markers = ("message", "comment", "inquiry", "detail", "content", "本文", "内容", "問い合わせ")
    for field in preview.fields:
        if any(marker in f"{field.name} {field.label}".lower() for marker in markers):
            values[field.name] = body
    missing = [
        field.label
        for field in preview.fields
        if field.required and not values.get(field.name, "").strip()
    ]
    return values, missing


def process_form_batch_item(db: Session, item: FormDeliveryBatchItem, user_id: UUID | None) -> bool:
    company = db.get(Company, item.company_id)
    draft = db.get(OutreachDraft, item.draft_id) if item.draft_id else None
    if company is None or draft is None:
        item.status, item.reason = "skipped", "送信対象ではありません。"
        return True
    permission = evaluate_contact_permission(
        db, company.project_id, company.id, "form", company.contact_url
    )
    if permission.status == "PROHIBITED":
        item.status, item.reason = "skipped", permission.message
        return True
    if permission.requires_review:
        item.status, item.reason = "manual_required", permission.message
        return True
    if db.scalar(
        select(FormDelivery.id).where(
            FormDelivery.company_id == company.id, FormDelivery.status == "submitted"
        )
    ):
        item.status, item.reason = "skipped", "この企業にはフォーム送信済みです。"
        return True
    context = None
    try:
        context = inspect_delivery_profile(db, company, draft)
        preview = context.preview
        values = context.values
        missing = required_missing(preview, values)
        if missing:
            item.status = "manual_required"
            item.reason = f"手動入力が必要です: {', '.join(missing[:3])}"
            return True
        preview, submission = submit_form(
            context.profile.form_url,
            values,
            form_index=context.profile.form_index,
            profile_fields=context.fields,
            form_profile_id=context.profile.id,
            expected_fingerprint=context.profile.fingerprint,
            confirmation_expected=context.profile.confirmation_page is True,
        )
    except FormDeliveryError as exc:
        if context is not None:
            mark_profile_changed(db, context.profile, exc)
        item.status, item.reason = "manual_required", exc.public_message
        return True
    except Exception:
        item.status, item.reason = "failed", "フォーム送信処理に失敗しました。"
        return False
    delivery = FormDelivery(
        draft_id=draft.id,
        company_id=company.id,
        form_profile_id=context.profile.id,
        created_by_user_id=user_id,
        form_url=preview.form_url,
        action_url=preview.action_url,
        delivery_method="direct",
        response_status=submission.response_status,
        final_url=submission.final_url,
        confirmation_used=submission.confirmation_used,
        completion_evidence=submission.completion_evidence,
        submitted_at=datetime.now(timezone.utc),
        profile_fingerprint=context.profile.fingerprint,
        field_mapping_snapshot=mapping_snapshot(context.fields),
    )
    db.add(delivery)
    db.flush()
    item.form_delivery_id = delivery.id
    item.status = "submitted"
    item.submitted_at = delivery.submitted_at
    db.add(
        OutreachDraftApproval(
            draft_id=draft.id,
            approved_by_user_id=user_id,
            approval_type="form_direct",
            subject=draft.subject,
            body=draft.body,
            delivered_at=delivery.submitted_at,
            experiment_id=draft.experiment_id,
            experiment_variant=draft.experiment_variant,
        )
    )
    db.add(
        Activity(
            company_id=company.id,
            activity_type="form",
            note=f"一括フォームDMを実行: {preview.form_url}",
        )
    )
    if company.status in {"unreviewed", "target"}:
        company.status = "approached"
        db.add(
            Activity(
                company_id=company.id,
                activity_type="status_change",
                note="営業状況を更新: アプローチ済（一括フォームDM）",
            )
        )
    return True
