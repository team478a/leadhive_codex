from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Activity,
    Company,
    FormDelivery,
    FormDeliveryBatch,
    FormDeliveryBatchItem,
    OutreachDraft,
    OutreachDraftApproval,
    OutreachTemplate,
    User,
)
from app.project_access import project_access
from app.schemas import (
    FormDeliveryBatchCreateInput,
    FormDeliveryBatchExecuteInput,
    FormDeliveryBatchItemOut,
    FormDeliveryBatchOut,
)
from app.security import current_user
from app.services.form_delivery import FormDeliveryError, FormPreview, inspect_form, submit_form

router = APIRouter(prefix="/api")


def batch_out(db: Session, batch: FormDeliveryBatch) -> FormDeliveryBatchOut:
    rows = db.execute(
        select(FormDeliveryBatchItem, Company)
        .join(Company, Company.id == FormDeliveryBatchItem.company_id)
        .where(FormDeliveryBatchItem.batch_id == batch.id)
        .order_by(FormDeliveryBatchItem.created_at, FormDeliveryBatchItem.id)
    ).all()
    return FormDeliveryBatchOut(
        id=batch.id,
        project_id=batch.project_id,
        template_id=batch.template_id,
        status=batch.status,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        items=[
            FormDeliveryBatchItemOut(
                id=item.id,
                company_id=item.company_id,
                draft_id=item.draft_id,
                form_delivery_id=item.form_delivery_id,
                status=item.status,
                reason=item.reason,
                submitted_at=item.submitted_at,
                created_at=item.created_at,
                company_name=company.company_name,
                form_url=company.contact_url,
            )
            for item, company in rows
        ],
    )


def body_values(preview: FormPreview, body: str) -> tuple[dict[str, str], list[str]]:
    values = {field.name: field.value for field in preview.fields if field.value}
    body_markers = (
        "message",
        "comment",
        "inquiry",
        "detail",
        "content",
        "本文",
        "内容",
        "問い合わせ",
    )
    for field in preview.fields:
        marker = f"{field.name} {field.label}".lower()
        if any(value in marker for value in body_markers):
            values[field.name] = body
    missing = [
        field.label
        for field in preview.fields
        if field.required and not values.get(field.name, "").strip()
    ]
    return values, missing


@router.get(
    "/projects/{project_id}/form-delivery-batches", response_model=list[FormDeliveryBatchOut]
)
def list_form_batches(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    batches = db.scalars(
        select(FormDeliveryBatch)
        .where(FormDeliveryBatch.project_id == project_id)
        .order_by(FormDeliveryBatch.created_at.desc())
        .limit(20)
    ).all()
    return [batch_out(db, batch) for batch in batches]


@router.post(
    "/projects/{project_id}/form-delivery-batches",
    response_model=FormDeliveryBatchOut,
    status_code=201,
)
def create_form_batch(
    project_id: UUID,
    body: FormDeliveryBatchCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    template = db.get(OutreachTemplate, body.template_id)
    if template is None or template.project_id != project_id or template.channel != "form":
        raise HTTPException(422, "このプロジェクトのフォーム文面テンプレートを選択してください。")
    companies = db.scalars(
        select(Company).where(Company.project_id == project_id, Company.id.in_(body.company_ids))
    ).all()
    if len(companies) != len(set(body.company_ids)):
        raise HTTPException(422, "対象企業にアクセスできません。")
    batch = FormDeliveryBatch(
        project_id=project_id, template_id=template.id, created_by_user_id=user.id
    )
    db.add(batch)
    db.flush()
    for company in companies:
        status, reason, draft_id = "queued", "", None
        if company.do_not_contact:
            status, reason = "skipped", "連絡禁止の企業です。"
        elif not company.contact_url:
            status, reason = "skipped", "問い合わせフォームURLがありません。"
        elif db.scalar(
            select(FormDelivery.id).where(
                FormDelivery.company_id == company.id, FormDelivery.status == "submitted"
            )
        ):
            status, reason = "skipped", "この企業にはフォーム送信済みです。"
        else:
            draft = OutreachDraft(
                company_id=company.id,
                created_by_user_id=user.id,
                channel="form",
                subject=template.subject,
                body=template.body,
            )
            db.add(draft)
            db.flush()
            draft_id = draft.id
        db.add(
            FormDeliveryBatchItem(
                batch_id=batch.id,
                company_id=company.id,
                draft_id=draft_id,
                status=status,
                reason=reason,
            )
        )
    db.commit()
    db.refresh(batch)
    return batch_out(db, batch)


@router.post("/form-delivery-batches/{batch_id}/execute", response_model=FormDeliveryBatchOut)
def execute_form_batch(
    batch_id: UUID,
    body: FormDeliveryBatchExecuteInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.confirmed:
        raise HTTPException(422, "対象件数と文面を確認して一括送信を承認してください。")
    batch = db.get(FormDeliveryBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "一括フォームDMが見つかりません。")
    project_access(batch.project_id, db, user)
    if batch.status in {"completed", "cancelled"}:
        raise HTTPException(409, "この一括フォームDMは終了しています。")
    batch.status = "running"
    db.commit()
    items = db.scalars(
        select(FormDeliveryBatchItem)
        .where(FormDeliveryBatchItem.batch_id == batch.id, FormDeliveryBatchItem.status == "queued")
        .order_by(FormDeliveryBatchItem.created_at)
        .limit(body.limit)
    ).all()
    for item in items:
        company = db.get(Company, item.company_id)
        draft = db.get(OutreachDraft, item.draft_id) if item.draft_id else None
        if company is None or draft is None or company.do_not_contact:
            item.status, item.reason = "skipped", "送信対象ではありません。"
            continue
        try:
            preview = inspect_form(company.contact_url)
            values, missing = body_values(preview, draft.body)
            if missing:
                item.status, item.reason = (
                    "manual_required",
                    f"手動入力が必要です: {', '.join(missing[:3])}",
                )
                continue
            preview, response_status = submit_form(company.contact_url, values)
        except FormDeliveryError as exc:
            item.status, item.reason = "manual_required", exc.public_message
            continue
        except Exception:
            item.status, item.reason = "failed", "フォーム送信処理に失敗しました。"
            continue
        delivery = FormDelivery(
            draft_id=draft.id,
            company_id=company.id,
            created_by_user_id=user.id,
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
                approved_by_user_id=user.id,
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
    remaining = db.scalar(
        select(FormDeliveryBatchItem.id)
        .where(FormDeliveryBatchItem.batch_id == batch.id, FormDeliveryBatchItem.status == "queued")
        .limit(1)
    )
    batch.status = "ready" if remaining else "completed"
    db.commit()
    db.refresh(batch)
    return batch_out(db, batch)


@router.post("/form-delivery-batches/{batch_id}/cancel", response_model=FormDeliveryBatchOut)
def cancel_form_batch(
    batch_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    batch = db.get(FormDeliveryBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "一括フォームDMが見つかりません。")
    project_access(batch.project_id, db, user)
    batch.status = "cancelled"
    db.commit()
    db.refresh(batch)
    return batch_out(db, batch)
