import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Activity,
    Company,
    ContactPerson,
    EmailDelivery,
    FormDelivery,
    FormProfileField,
    OutreachDraft,
    OutreachDraftApproval,
    OutreachTemplate,
    Project,
    User,
)
from app.project_access import company_access as owned_company
from app.project_access import project_access
from app.schemas import (
    EmailDeliveryCreateInput,
    EmailDeliveryListItemOut,
    EmailDeliveryListOut,
    EmailDeliveryOut,
    EmailDeliveryRetryInput,
    FormAssistDeliveryInput,
    FormAssistOut,
    FormDeliveryCreateInput,
    FormDeliveryOut,
    FormFieldOut,
    FormPreviewOut,
    OutreachDraftApprovalOut,
    OutreachDraftGenerateInput,
    OutreachDraftOut,
    OutreachDraftUpdateInput,
    OutreachTemplateApplyInput,
    OutreachTemplateInput,
    OutreachTemplateOut,
)
from app.security import current_user
from app.services.ai import AiAnalysisError, OutreachContext, get_ai_provider
from app.services.contact_permission import (
    ContactPermissionDecision,
    evaluate_contact_permission,
)
from app.services.form_codex import build_codex_form_payload
from app.services.form_delivery import FormDeliveryError, submit_form
from app.services.form_profile_delivery import (
    inspect_delivery_profile,
    mapping_snapshot,
    mark_profile_changed,
    primary_form_profile,
    profile_form_url,
)

logger = logging.getLogger("leadhive")
router = APIRouter(prefix="/api")


def owned_draft(draft_id: UUID, db: Session, user: User, write: bool = True) -> OutreachDraft:
    draft = db.get(OutreachDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "営業文面が見つかりません。")
    owned_company(draft.company_id, db, user, write=write)
    return draft


def owned_email_delivery(
    delivery_id: UUID, db: Session, user: User, write: bool = True
) -> EmailDelivery:
    delivery = db.get(EmailDelivery, delivery_id)
    if delivery is None:
        raise HTTPException(404, "メール送信が見つかりません。")
    owned_company(delivery.company_id, db, user, write=write)
    return delivery


def record_draft_approval(
    db: Session,
    draft: OutreachDraft,
    user: User,
    approval_type: str,
    *,
    delivered_at: datetime | None = None,
) -> OutreachDraftApproval:
    approval = OutreachDraftApproval(
        draft_id=draft.id,
        approved_by_user_id=user.id,
        approval_type=approval_type,
        subject=draft.subject,
        body=draft.body,
        delivered_at=delivered_at,
        experiment_id=draft.experiment_id,
        experiment_variant=draft.experiment_variant,
    )
    db.add(approval)
    return approval


@router.get("/projects/{project_id}/outreach-templates", response_model=list[OutreachTemplateOut])
def list_outreach_templates(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    return db.scalars(
        select(OutreachTemplate)
        .where(OutreachTemplate.project_id == project_id)
        .order_by(OutreachTemplate.name, OutreachTemplate.id)
    ).all()


@router.post(
    "/projects/{project_id}/outreach-templates",
    response_model=OutreachTemplateOut,
    status_code=201,
)
def create_outreach_template(
    project_id: UUID,
    body: OutreachTemplateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    template = OutreachTemplate(
        project_id=project_id, created_by_user_id=user.id, **body.model_dump()
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/outreach-templates/{template_id}", status_code=204)
def delete_outreach_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    template = db.get(OutreachTemplate, template_id)
    if template is None:
        raise HTTPException(404, "営業文面テンプレートが見つかりません。")
    project_access(template.project_id, db, user)
    db.delete(template)
    db.commit()


@router.get("/projects/{project_id}/email-deliveries", response_model=EmailDeliveryListOut)
def list_email_deliveries(
    project_id: UUID,
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    rows = db.execute(
        select(EmailDelivery, Company.company_name)
        .join(Company, Company.id == EmailDelivery.company_id)
        .where(Company.project_id == project_id)
        .order_by(EmailDelivery.created_at.desc(), EmailDelivery.id.desc())
        .limit(limit)
    ).all()
    counts = {status: 0 for status in ("queued", "running", "sent", "failed", "cancelled")}
    count_rows = db.execute(
        select(EmailDelivery.status, func.count())
        .join(Company, Company.id == EmailDelivery.company_id)
        .where(Company.project_id == project_id)
        .group_by(EmailDelivery.status)
    ).all()
    counts.update(dict(count_rows))
    return EmailDeliveryListOut(
        items=[
            EmailDeliveryListItemOut(
                **EmailDeliveryOut.model_validate(delivery).model_dump(), company_name=company_name
            )
            for delivery, company_name in rows
        ],
        queued_count=counts["queued"],
        running_count=counts["running"],
        sent_count=counts["sent"],
        failed_count=counts["failed"],
        cancelled_count=counts["cancelled"],
    )


def delivery_time(value: datetime | None) -> datetime:
    now = datetime.now(timezone.utc)
    scheduled_for = value or now
    if scheduled_for.tzinfo is None:
        raise HTTPException(422, "送信日時にはタイムゾーンを指定してください。")
    if scheduled_for < now - timedelta(minutes=1):
        raise HTTPException(422, "過去の日時には送信予約できません。")
    if scheduled_for > now + timedelta(days=90):
        raise HTTPException(422, "送信予約は90日以内にしてください。")
    return scheduled_for


def valid_recipient(company: Company, draft: OutreachDraft, db: Session, email: str) -> str:
    normalized = email.casefold()
    if company.email and company.email.casefold() == normalized:
        return company.company_name
    contacts = db.scalars(
        select(ContactPerson).where(
            ContactPerson.company_id == company.id,
            ContactPerson.verification_status != "invalid",
        )
    ).all()
    for contact in contacts:
        if contact.email and contact.email.casefold() == normalized:
            return contact.name
    if draft.contact_person_id:
        contact = db.get(ContactPerson, draft.contact_person_id)
        if contact and contact.email and contact.email.casefold() == normalized:
            return contact.name
    raise HTTPException(
        409, "企業または有効な先方担当者に登録されたメールアドレスを選択してください。"
    )


def validate_channel(company: Company, channel: str):
    available = {
        "email": bool(company.email),
        "form": bool(company.contact_url),
        "sns": any(
            (
                company.instagram_url,
                company.x_url,
                company.tiktok_url,
                company.facebook_url,
                company.line_url,
            )
        ),
    }
    if not available[channel]:
        raise HTTPException(409, "選択した連絡経路の連絡先が登録されていません。")


def require_contact_permission(
    db: Session,
    company: Company,
    channel: str,
    destination: str = "",
    *,
    allow_uncertain: bool = False,
) -> ContactPermissionDecision:
    decision = evaluate_contact_permission(db, company.project_id, company.id, channel, destination)
    if decision.status == "PROHIBITED" or (decision.status == "UNCERTAIN" and not allow_uncertain):
        status_code = 409 if decision.status == "PROHIBITED" else 422
        raise HTTPException(status_code, decision.message)
    return decision


@router.get("/companies/{company_id}/outreach-drafts", response_model=list[OutreachDraftOut])
def list_outreach_drafts(
    company_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_company(company_id, db, user, write=False)
    return db.scalars(
        select(OutreachDraft)
        .where(OutreachDraft.company_id == company_id)
        .order_by(OutreachDraft.created_at.desc(), OutreachDraft.id.desc())
        .limit(50)
    ).all()


@router.get("/outreach-drafts/{draft_id}/approvals", response_model=list[OutreachDraftApprovalOut])
def list_outreach_draft_approvals(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user, write=False)
    return db.scalars(
        select(OutreachDraftApproval)
        .where(OutreachDraftApproval.draft_id == draft.id)
        .order_by(OutreachDraftApproval.approved_at.desc(), OutreachDraftApproval.id.desc())
        .limit(50)
    ).all()


@router.post("/outreach-drafts/{draft_id}/apply-template", response_model=OutreachDraftOut)
def apply_outreach_template(
    draft_id: UUID,
    body: OutreachTemplateApplyInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user)
    company = db.get(Company, draft.company_id)
    template = db.get(OutreachTemplate, body.template_id)
    if company is None or template is None or template.project_id != company.project_id:
        raise HTTPException(404, "営業文面テンプレートが見つかりません。")
    if template.channel != draft.channel:
        raise HTTPException(409, "同じ連絡経路のテンプレートだけを適用できます。")
    draft.subject = template.subject
    draft.body = template.body
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/outreach-drafts/{draft_id}/email-delivery", response_model=EmailDeliveryOut | None)
def get_email_delivery(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user, write=False)
    return db.scalar(select(EmailDelivery).where(EmailDelivery.draft_id == draft.id))


@router.get("/outreach-drafts/{draft_id}/form-preview", response_model=FormPreviewOut)
def get_form_preview(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user, write=False)
    if draft.channel != "form":
        raise HTTPException(409, "フォーム文面だけを送信できます。")
    company = db.get(Company, draft.company_id)
    if company is None:
        raise HTTPException(409, "企業情報が見つかりません。")
    require_contact_permission(db, company, "form", company.contact_url)
    try:
        context = inspect_delivery_profile(db, company, draft)
        preview = context.preview
    except FormDeliveryError as exc:
        raise HTTPException(422, exc.public_message) from exc
    return FormPreviewOut(
        form_url=preview.form_url,
        action_url=preview.action_url,
        fields=[FormFieldOut(**field.__dict__) for field in preview.fields],
        form_profile_id=preview.form_profile_id,
        form_status=preview.form_status,
        fingerprint=preview.fingerprint,
    )


@router.get("/outreach-drafts/{draft_id}/form-assist", response_model=FormAssistOut)
def get_form_assist(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user, write=False)
    if draft.channel != "form":
        raise HTTPException(409, "フォーム文面だけをCodex支援へ渡せます。")
    company = db.get(Company, draft.company_id)
    if company is None:
        raise HTTPException(409, "企業情報が見つかりません。")
    require_contact_permission(db, company, "form", company.contact_url, allow_uncertain=True)
    try:
        form_url = profile_form_url(db, company)
    except FormDeliveryError as exc:
        raise HTTPException(409, exc.public_message) from exc
    if not form_url:
        raise HTTPException(409, "問い合わせフォームURLが登録されていません。")
    payload = build_codex_form_payload(db, company, draft)
    return FormAssistOut(
        task_reference=f"draft:{draft.id}",
        skill_name=payload.skill_name,
        company_name=company.company_name,
        form_url=form_url,
        subject=payload.subject,
        body=draft.body,
        reason=payload.reason,
        sender_values=payload.sender_values,
        fields=payload.fields,
        instructions=payload.instructions,
    )


@router.get("/outreach-drafts/{draft_id}/form-delivery", response_model=FormDeliveryOut | None)
def get_form_delivery(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user, write=False)
    return db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id))


@router.post(
    "/outreach-drafts/{draft_id}/form-assist-delivery",
    response_model=FormDeliveryOut,
    status_code=201,
)
def record_form_assist_delivery(
    draft_id: UUID,
    body: FormAssistDeliveryInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.confirmed:
        raise HTTPException(422, "Codex上で確認した送信結果を承認してください。")
    draft = owned_draft(draft_id, db, user)
    if draft.channel != "form":
        raise HTTPException(409, "フォーム文面だけをCodex支援送信として記録できます。")
    company = db.get(Company, draft.company_id)
    if company is None:
        raise HTTPException(409, "企業情報が見つかりません。")
    if body.status != "failed":
        require_contact_permission(db, company, "form", company.contact_url, allow_uncertain=True)
        try:
            form_url = profile_form_url(db, company)
        except FormDeliveryError as exc:
            raise HTTPException(409, exc.public_message) from exc
    else:
        profile = primary_form_profile(db, company.id)
        form_url = profile.form_url if profile and profile.form_found else company.contact_url
    if not form_url:
        raise HTTPException(409, "問い合わせフォームURLが登録されていません。")
    delivery = db.scalar(select(FormDelivery).where(FormDelivery.draft_id == draft.id))
    if delivery is not None and delivery.delivery_method != "codex_assisted":
        raise HTTPException(409, "この文面はLeadHiveから既にフォーム送信済みです。")
    if delivery is not None and delivery.status == "submitted":
        raise HTTPException(409, "この文面は既にフォーム送信済みです。")
    submitted_at = datetime.now(timezone.utc) if body.status == "submitted" else None
    profile = primary_form_profile(db, company.id)
    profile_fields = (
        list(
            db.scalars(
                select(FormProfileField)
                .where(FormProfileField.form_profile_id == profile.id)
                .order_by(FormProfileField.position)
            ).all()
        )
        if profile
        else []
    )
    if delivery is None:
        delivery = FormDelivery(
            draft_id=draft.id,
            company_id=company.id,
            created_by_user_id=user.id,
            form_url=form_url,
            delivery_method="codex_assisted",
            status=body.status,
            submitted_at=submitted_at,
            result_note=body.note,
            form_profile_id=profile.id if profile else None,
            profile_fingerprint=profile.fingerprint if profile else "",
            field_mapping_snapshot=mapping_snapshot(profile_fields),
        )
        db.add(delivery)
    else:
        delivery.status = body.status
        delivery.submitted_at = submitted_at
        delivery.result_note = body.note
        delivery.form_url = form_url
        delivery.form_profile_id = profile.id if profile else None
        delivery.profile_fingerprint = profile.fingerprint if profile else ""
        delivery.field_mapping_snapshot = mapping_snapshot(profile_fields)
    if body.status == "submitted":
        record_draft_approval(db, draft, user, "form_codex", delivered_at=submitted_at)
    outcome_label = {"pending": "保留", "submitted": "送信済み", "failed": "失敗"}[body.status]
    note = f"Codex支援フォーム送信を{outcome_label}として記録: {form_url}"
    if body.note:
        note = f"{note}（{body.note}）"
    db.add(Activity(company_id=company.id, activity_type="form", note=note))
    if body.status == "submitted" and company.status in {"unreviewed", "target"}:
        company.status = "approached"
        db.add(
            Activity(
                company_id=company.id,
                activity_type="status_change",
                note="営業状況を更新: アプローチ済（Codex支援フォーム送信）",
            )
        )
    db.commit()
    db.refresh(delivery)
    logger.info(
        "Codex-assisted form delivery recorded: id=%s company_id=%s status=%s",
        delivery.id,
        company.id,
        delivery.status,
    )
    return delivery


@router.post(
    "/outreach-drafts/{draft_id}/form-delivery", response_model=FormDeliveryOut, status_code=201
)
def create_form_delivery(
    draft_id: UUID,
    body: FormDeliveryCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.confirmed:
        raise HTTPException(422, "送信内容を確認して承認してください。")
    draft = owned_draft(draft_id, db, user)
    if draft.channel != "form":
        raise HTTPException(409, "フォーム文面だけを送信できます。")
    company = db.get(Company, draft.company_id)
    if company is None:
        raise HTTPException(409, "企業情報が見つかりません。")
    require_contact_permission(db, company, "form", company.contact_url)
    if db.scalar(select(FormDelivery.id).where(FormDelivery.draft_id == draft.id)):
        raise HTTPException(409, "この文面は既にフォーム送信済みです。")
    context = None
    try:
        context = inspect_delivery_profile(db, company, draft)
        preview, submission = submit_form(
            context.profile.form_url,
            body.field_values,
            form_index=context.profile.form_index,
            profile_fields=context.fields,
            form_profile_id=context.profile.id,
            expected_fingerprint=context.profile.fingerprint,
            confirmation_expected=context.profile.confirmation_page is True,
        )
    except FormDeliveryError as exc:
        if context is not None:
            mark_profile_changed(db, context.profile, exc)
        logger.warning(
            "form delivery failed: company_id=%s type=%s", company.id, type(exc).__name__
        )
        raise HTTPException(422, exc.public_message) from exc
    delivery = FormDelivery(
        draft_id=draft.id,
        company_id=company.id,
        form_profile_id=context.profile.id,
        created_by_user_id=user.id,
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
    record_draft_approval(db, draft, user, "form_direct", delivered_at=delivery.submitted_at)
    db.add(
        Activity(
            company_id=company.id,
            activity_type="form",
            note=f"フォーム送信を実行: {preview.form_url}",
        )
    )
    if company.status in {"unreviewed", "target"}:
        company.status = "approached"
        db.add(
            Activity(
                company_id=company.id,
                activity_type="status_change",
                note="営業状況を更新: アプローチ済（フォーム送信）",
            )
        )
    db.commit()
    db.refresh(delivery)
    logger.info("form delivery submitted: id=%s company_id=%s", delivery.id, company.id)
    return delivery


@router.post(
    "/outreach-drafts/{draft_id}/email-delivery",
    response_model=EmailDeliveryOut,
    status_code=202,
)
def create_email_delivery(
    draft_id: UUID,
    body: EmailDeliveryCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.confirmed:
        raise HTTPException(422, "送信内容を確認して承認してください。")
    draft = owned_draft(draft_id, db, user)
    if draft.channel != "email":
        raise HTTPException(409, "メール文面だけを送信できます。")
    if not draft.subject.strip() or not draft.body.strip():
        raise HTTPException(409, "件名と本文を入力してください。")
    company = db.get(Company, draft.company_id)
    if company is None:
        raise HTTPException(409, "企業情報が見つかりません。")
    existing = db.scalar(select(EmailDelivery).where(EmailDelivery.draft_id == draft.id))
    if existing:
        raise HTTPException(409, "この文面は既に送信予約または送信済みです。")
    recipient_email = str(body.recipient_email)
    require_contact_permission(db, company, "email", recipient_email)
    delivery = EmailDelivery(
        draft_id=draft.id,
        company_id=company.id,
        created_by_user_id=user.id,
        recipient_email=recipient_email,
        recipient_name=valid_recipient(company, draft, db, recipient_email),
        subject=draft.subject,
        body=draft.body,
        scheduled_for=delivery_time(body.scheduled_for),
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(delivery)
    record_draft_approval(db, draft, user, "email")
    db.commit()
    db.refresh(delivery)
    logger.info("email delivery queued: id=%s company_id=%s", delivery.id, company.id)
    return delivery


@router.post("/email-deliveries/{delivery_id}/cancel", response_model=EmailDeliveryOut)
def cancel_email_delivery(
    delivery_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    delivery = owned_email_delivery(delivery_id, db, user)
    if delivery.status != "queued":
        raise HTTPException(409, "待機中のメール送信だけをキャンセルできます。")
    delivery.status = "cancelled"
    delivery.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(delivery)
    return delivery


@router.post("/email-deliveries/{delivery_id}/retry", response_model=EmailDeliveryOut)
def retry_email_delivery(
    delivery_id: UUID,
    body: EmailDeliveryRetryInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.confirmed:
        raise HTTPException(422, "再送内容を確認して承認してください。")
    delivery = owned_email_delivery(delivery_id, db, user)
    if delivery.status != "failed":
        raise HTTPException(409, "失敗したメール送信だけを再送できます。")
    company = db.get(Company, delivery.company_id)
    if company is None:
        raise HTTPException(409, "削除済みの企業には再送できません。")
    require_contact_permission(db, company, "email", delivery.recipient_email)
    delivery.status = "queued"
    delivery.scheduled_for = delivery_time(body.scheduled_for)
    delivery.confirmed_at = datetime.now(timezone.utc)
    delivery.started_at = None
    delivery.finished_at = None
    delivery.worker_id = None
    delivery.lease_expires_at = None
    delivery.error_message = ""
    db.commit()
    db.refresh(delivery)
    logger.info("email delivery retried: id=%s", delivery.id)
    return delivery


@router.post(
    "/companies/{company_id}/outreach-drafts/generate",
    response_model=OutreachDraftOut,
    status_code=201,
)
def generate_outreach_draft(
    company_id: UUID,
    body: OutreachDraftGenerateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = owned_company(company_id, db, user)
    if company.ai_status != "completed":
        raise HTTPException(409, "先にAI企業分析を完了してください。")
    validate_channel(company, body.channel)
    destination = company.email if body.channel == "email" else company.contact_url
    require_contact_permission(
        db,
        company,
        body.channel,
        destination,
        allow_uncertain=body.channel == "form",
    )
    project = db.get(Project, company.project_id)
    if project is None:
        raise HTTPException(409, "プロジェクトが見つかりません。")

    contact = None
    if body.contact_person_id:
        contact = db.get(ContactPerson, body.contact_person_id)
        if contact is None or contact.company_id != company.id:
            raise HTTPException(404, "担当者情報が見つかりません。")
        if contact.verification_status == "invalid":
            raise HTTPException(409, "無効な担当者は宛先に指定できません。")

    context = OutreachContext(
        channel=body.channel,
        company_name=company.company_name,
        recipient_name=contact.name if contact else "",
        recipient_department=contact.department if contact else "",
        recipient_title=contact.title if contact else "",
        business_summary=company.business_summary,
        ai_summary=company.ai_summary,
        ai_strengths=company.ai_strengths,
        ai_concerns=company.ai_concerns,
        recommended_approach=company.ai_recommended_approach,
        sales_objective=project.sales_objective,
        instruction=body.instruction,
    )
    try:
        provider = get_ai_provider()
        content = provider.generate_outreach(context)
    except AiAnalysisError as exc:
        logger.warning("AI error: company_id=%s type=%s", company.id, type(exc).__name__)
        raise HTTPException(503, exc.public_message) from exc

    draft = OutreachDraft(
        company_id=company.id,
        created_by_user_id=user.id,
        contact_person_id=contact.id if contact else None,
        channel=body.channel,
        subject=content.subject if body.channel == "email" else "",
        body=content.body,
        ai_provider=provider.name,
        ai_model=provider.model,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    logger.info("outreach draft generated: company_id=%s channel=%s", company.id, body.channel)
    return draft


@router.put("/outreach-drafts/{draft_id}", response_model=OutreachDraftOut)
def update_outreach_draft(
    draft_id: UUID,
    body: OutreachDraftUpdateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user)
    draft.subject = body.subject if draft.channel == "email" else ""
    draft.body = body.body
    db.commit()
    db.refresh(draft)
    return draft


@router.delete("/outreach-drafts/{draft_id}", status_code=204)
def delete_outreach_draft(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user)
    db.delete(draft)
    db.commit()
