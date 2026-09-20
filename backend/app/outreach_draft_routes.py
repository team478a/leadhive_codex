import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_routes import owned_company
from app.database import get_db
from app.models import Company, ContactPerson, OutreachDraft, Project, User
from app.schemas import (
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
