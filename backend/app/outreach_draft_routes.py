import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis_routes import owned_company
from app.database import get_db
from app.models import Company, ContactPerson, EmailDelivery, OutreachDraft, Project, User
from app.project_access import project_access
from app.schemas import (
    EmailDeliveryCreateInput,
    EmailDeliveryListItemOut,
    EmailDeliveryListOut,
    EmailDeliveryOut,
    EmailDeliveryRetryInput,
    OutreachDraftGenerateInput,
    OutreachDraftOut,
    OutreachDraftUpdateInput,
)
from app.security import current_user
from app.services.ai import AiAnalysisError, OutreachContext, get_ai_provider

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


@router.get("/outreach-drafts/{draft_id}/email-delivery", response_model=EmailDeliveryOut | None)
def get_email_delivery(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    draft = owned_draft(draft_id, db, user, write=False)
    return db.scalar(select(EmailDelivery).where(EmailDelivery.draft_id == draft.id))


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
    if company.do_not_contact:
        raise HTTPException(409, "連絡禁止の企業にはメール送信できません。")
    existing = db.scalar(select(EmailDelivery).where(EmailDelivery.draft_id == draft.id))
    if existing:
        raise HTTPException(409, "この文面は既に送信予約または送信済みです。")
    recipient_email = str(body.recipient_email)
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
    if company is None or company.do_not_contact:
        raise HTTPException(409, "連絡禁止または削除済みの企業には再送できません。")
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
    if company.do_not_contact:
        raise HTTPException(409, "連絡禁止の企業には営業文面を生成できません。")
    if company.ai_status != "completed":
        raise HTTPException(409, "先にAI企業分析を完了してください。")
    validate_channel(company, body.channel)
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
