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
from app.services.form_delivery import FormDeliveryError, FormPreview, inspect_form, submit_form


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
    if company is None or draft is None or company.do_not_contact:
        item.status, item.reason = "skipped", "送信対象ではありません。"
        return True
    if db.scalar(
        select(FormDelivery.id).where(
            FormDelivery.company_id == company.id, FormDelivery.status == "submitted"
        )
    ):
        item.status, item.reason = "skipped", "この企業にはフォーム送信済みです。"
        return True
    try:
        preview = inspect_form(company.contact_url)
        values, missing = body_values(preview, draft.body)
        if missing:
            item.status = "manual_required"
            item.reason = f"手動入力が必要です: {', '.join(missing[:3])}"
            return True
        preview, response_status = submit_form(company.contact_url, values)
    except FormDeliveryError as exc:
        item.status, item.reason = "manual_required", exc.public_message
        return True
    except Exception:
        item.status, item.reason = "failed", "フォーム送信処理に失敗しました。"
        return False
    delivery = FormDelivery(
        draft_id=draft.id,
        company_id=company.id,
        created_by_user_id=user_id,
        form_url=preview.form_url,
        action_url=preview.action_url,
        delivery_method="direct",
        response_status=response_status,
        submitted_at=datetime.now(timezone.utc),
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
