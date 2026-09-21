from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Activity,
    Company,
    FormDelivery,
    FormDeliveryBatch,
    FormDeliveryBatchItem,
    OperationJob,
    OutreachDraft,
    OutreachDraftApproval,
    OutreachTemplate,
    User,
)
from app.project_access import project_access
from app.schemas import (
    FormCodexTaskOut,
    FormCodexTaskUpdateInput,
    FormDeliveryBatchCreateInput,
    FormDeliveryBatchExecuteInput,
    FormDeliveryBatchItemOut,
    FormDeliveryBatchItemRetryInput,
    FormDeliveryBatchOut,
)
from app.security import current_user

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
        operation_job_id=batch.operation_job_id,
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


@router.get("/projects/{project_id}/form-codex-queue", response_model=list[FormCodexTaskOut])
def list_form_codex_queue(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    rows = db.execute(
        select(FormDeliveryBatchItem, FormDeliveryBatch, Company, OutreachDraft)
        .join(FormDeliveryBatch, FormDeliveryBatch.id == FormDeliveryBatchItem.batch_id)
        .join(Company, Company.id == FormDeliveryBatchItem.company_id)
        .join(OutreachDraft, OutreachDraft.id == FormDeliveryBatchItem.draft_id)
        .where(
            FormDeliveryBatch.project_id == project_id,
            FormDeliveryBatch.status != "cancelled",
            FormDeliveryBatchItem.status == "manual_required",
        )
        .order_by(FormDeliveryBatchItem.created_at, FormDeliveryBatchItem.id)
        .limit(100)
    ).all()
    return [
        FormCodexTaskOut(
            item_id=item.id,
            batch_id=batch.id,
            company_id=company.id,
            company_name=company.company_name,
            form_url=company.contact_url,
            body=draft.body,
            reason=item.reason,
            instructions=(
                "Codexのコンピューター操作でフォームを開き、本文を入力してください。"
                "CAPTCHA、送信前確認、規約同意、最終送信は人が画面で確認し、"
                "送信後はLeadHiveの企業詳細で結果を記録します。"
            ),
            codex_status=item.codex_status,
            codex_assignee=item.codex_assignee,
        )
        for item, batch, company, draft in rows
    ]


@router.post("/form-codex-queue/{item_id}", response_model=FormCodexTaskOut)
def update_form_codex_task(
    item_id: UUID,
    body: FormCodexTaskUpdateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    item = db.get(FormDeliveryBatchItem, item_id)
    if item is None:
        raise HTTPException(404, "Codex支援フォームが見つかりません。")
    batch = db.get(FormDeliveryBatch, item.batch_id)
    if batch is None:
        raise HTTPException(404, "一括フォームDMが見つかりません。")
    project_access(batch.project_id, db, user)
    if item.status != "manual_required":
        raise HTTPException(409, "Codex支援が必要なフォームだけを更新できます。")
    if body.status in {"submitted", "failed"} and not body.confirmed:
        raise HTTPException(422, "Codex上で確認した結果を承認してください。")
    company = db.get(Company, item.company_id)
    draft = db.get(OutreachDraft, item.draft_id) if item.draft_id else None
    if company is None or draft is None:
        raise HTTPException(409, "送信対象の情報が見つかりません。")
    item.codex_status = body.status
    item.codex_assignee = user.email
    if body.status == "running":
        db.commit()
    elif body.status == "submitted":
        delivery = db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id))
        if delivery and delivery.delivery_method != "codex_assisted":
            raise HTTPException(409, "この文面はLeadHiveから既にフォーム送信済みです。")
        sent_at = datetime.now(timezone.utc)
        if delivery is None:
            delivery = FormDelivery(
                draft_id=draft.id,
                company_id=company.id,
                created_by_user_id=user.id,
                form_url=company.contact_url,
                delivery_method="codex_assisted",
                status="submitted",
                submitted_at=sent_at,
                result_note=body.note,
            )
            db.add(delivery)
            db.flush()
        else:
            delivery.status, delivery.submitted_at, delivery.result_note = (
                "submitted",
                sent_at,
                body.note,
            )
        item.status, item.form_delivery_id, item.submitted_at = "submitted", delivery.id, sent_at
        db.add(
            OutreachDraftApproval(
                draft_id=draft.id,
                approved_by_user_id=user.id,
                approval_type="form_codex",
                subject=draft.subject,
                body=draft.body,
                delivered_at=sent_at,
                experiment_id=draft.experiment_id,
                experiment_variant=draft.experiment_variant,
            )
        )
        db.add(
            Activity(
                company_id=company.id, activity_type="form", note="Codex支援フォーム送信を記録"
            )
        )
        if company.status in {"unreviewed", "target"}:
            company.status = "approached"
            db.add(
                Activity(
                    company_id=company.id,
                    activity_type="status_change",
                    note="営業状況を更新: アプローチ済（Codex支援フォーム送信）",
                )
            )
        db.commit()
    else:
        item.status, item.reason = "failed", body.note or "Codex支援フォーム送信に失敗しました。"
        db.add(
            Activity(
                company_id=company.id,
                activity_type="form",
                note=f"Codex支援フォーム送信に失敗: {item.reason}",
            )
        )
        db.commit()
    return FormCodexTaskOut(
        item_id=item.id,
        batch_id=batch.id,
        company_id=company.id,
        company_name=company.company_name,
        form_url=company.contact_url,
        body=draft.body,
        reason=item.reason,
        instructions="Codex支援フォームの結果をLeadHiveへ記録します。",
        codex_status=item.codex_status,
        codex_assignee=item.codex_assignee,
    )


@router.post("/form-delivery-batch-items/{item_id}/retry", response_model=FormDeliveryBatchOut)
def retry_form_batch_item(
    item_id: UUID,
    body: FormDeliveryBatchItemRetryInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.confirmed:
        raise HTTPException(422, "対象フォームを確認して再試行を承認してください。")
    item = db.get(FormDeliveryBatchItem, item_id)
    if item is None:
        raise HTTPException(404, "一括フォームDMの対象が見つかりません。")
    batch = db.get(FormDeliveryBatch, item.batch_id)
    if batch is None:
        raise HTTPException(404, "一括フォームDMが見つかりません。")
    project_access(batch.project_id, db, user)
    if item.status != "failed":
        raise HTTPException(409, "失敗したフォーム送信だけを再試行できます。")
    if batch.status == "cancelled":
        raise HTTPException(409, "中止済みの一括フォームDMは再試行できません。")
    item.status = "queued"
    item.reason = ""
    item.submitted_at = None
    batch.status = "ready"
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
    active = db.scalar(
        select(OperationJob.id).where(
            OperationJob.operation_type == "form_delivery",
            OperationJob.status.in_(("queued", "running")),
            OperationJob.payload["batch_id"].astext == str(batch.id),
        )
    )
    if active:
        raise HTTPException(409, "この一括フォームDMはすでに実行待ちです。")
    queued_count = (
        db.scalar(
            select(func.count())
            .select_from(FormDeliveryBatchItem)
            .where(
                FormDeliveryBatchItem.batch_id == batch.id,
                FormDeliveryBatchItem.status == "queued",
            )
        )
        or 0
    )
    if not queued_count:
        raise HTTPException(409, "送信待ちのフォームがありません。")
    job = OperationJob(
        project_id=batch.project_id,
        operation_type="form_delivery",
        payload={
            "batch_id": str(batch.id),
            "limit": body.limit,
            "created_by_user_id": str(user.id),
        },
    )
    batch.status = "running"
    db.add(job)
    db.flush()
    batch.operation_job_id = job.id
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
    if batch.operation_job_id:
        job = db.get(OperationJob, batch.operation_job_id)
        if job and job.status == "queued":
            job.status = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
        elif job and job.status == "running":
            job.cancel_requested = True
    db.commit()
    db.refresh(batch)
    return batch_out(db, batch)
