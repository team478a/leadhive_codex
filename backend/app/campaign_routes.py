from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Company,
    EmailCampaign,
    EmailDelivery,
    OutreachConversion,
    OutreachDraft,
    OutreachDraftApproval,
    OutreachTemplate,
    SuppressionEntry,
    User,
)
from app.project_access import project_access
from app.schemas import EmailCampaignCreateInput, EmailCampaignOut
from app.security import current_user
from app.services.contact_permission import evaluate_contact_permission

router = APIRouter(prefix="/api")


def campaign_out(db: Session, campaign: EmailCampaign) -> EmailCampaignOut:
    counts = dict(
        db.execute(
            select(EmailDelivery.status, func.count())
            .where(EmailDelivery.campaign_id == campaign.id)
            .group_by(EmailDelivery.status)
        ).all()
    )
    outcomes = dict(
        db.execute(
            select(
                OutreachConversion.outcome,
                func.count(func.distinct(OutreachConversion.approval_id)),
            )
            .select_from(EmailDelivery)
            .join(OutreachDraftApproval, OutreachDraftApproval.draft_id == EmailDelivery.draft_id)
            .outerjoin(
                OutreachConversion, OutreachConversion.approval_id == OutreachDraftApproval.id
            )
            .where(EmailDelivery.campaign_id == campaign.id, EmailDelivery.status == "sent")
            .group_by(OutreachConversion.outcome)
        ).all()
    )
    return EmailCampaignOut(
        id=campaign.id,
        project_id=campaign.project_id,
        template_id=campaign.template_id,
        name=campaign.name,
        status=campaign.status,
        followup_days=campaign.followup_days,
        queued_count=counts.get("queued", 0) + counts.get("running", 0),
        sent_count=counts.get("sent", 0),
        failed_count=counts.get("failed", 0),
        skipped_count=max(0, campaign.requested_count - sum(counts.values())),
        replied_count=outcomes.get("replied", 0),
        meeting_count=outcomes.get("meeting", 0),
        won_count=outcomes.get("won", 0),
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


@router.get("/projects/{project_id}/email-campaigns", response_model=list[EmailCampaignOut])
def list_campaigns(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    campaigns = db.scalars(
        select(EmailCampaign)
        .where(EmailCampaign.project_id == project_id)
        .order_by(EmailCampaign.created_at.desc())
        .limit(50)
    ).all()
    return [campaign_out(db, campaign) for campaign in campaigns]


@router.post(
    "/projects/{project_id}/email-campaigns", response_model=EmailCampaignOut, status_code=201
)
def create_campaign(
    project_id: UUID,
    body: EmailCampaignCreateInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not body.confirmed:
        raise HTTPException(422, "対象企業と文面を確認して一括メール送信を承認してください。")
    project_access(project_id, db, user)
    template = db.get(OutreachTemplate, body.template_id)
    if template is None or template.project_id != project_id or template.channel != "email":
        raise HTTPException(422, "このプロジェクトのメール文面テンプレートを選択してください。")
    companies = db.scalars(
        select(Company).where(Company.project_id == project_id, Company.id.in_(body.company_ids))
    ).all()
    if len(companies) != len(set(body.company_ids)):
        raise HTTPException(422, "対象企業にアクセスできません。")
    campaign = EmailCampaign(
        project_id=project_id,
        template_id=template.id,
        created_by_user_id=user.id,
        name=body.name,
        followup_days=body.followup_days,
        requested_count=len(body.company_ids),
    )
    db.add(campaign)
    db.flush()
    scheduled_for = body.scheduled_for or datetime.now(timezone.utc)
    for company in companies:
        permission = evaluate_contact_permission(db, project_id, company.id, "email", company.email)
        if not permission.allowed:
            continue
        exists = db.scalar(
            select(EmailDelivery.id)
            .where(
                EmailDelivery.company_id == company.id,
                EmailDelivery.status.in_(("queued", "running", "sent")),
            )
            .limit(1)
        )
        if exists:
            continue
        draft = OutreachDraft(
            company_id=company.id,
            created_by_user_id=user.id,
            channel="email",
            subject=template.subject,
            body=template.body,
        )
        db.add(draft)
        db.flush()
        delivery = EmailDelivery(
            draft_id=draft.id,
            company_id=company.id,
            created_by_user_id=user.id,
            recipient_email=company.email,
            recipient_name=company.company_name,
            subject=template.subject,
            body=template.body,
            scheduled_for=scheduled_for,
            confirmed_at=datetime.now(timezone.utc),
            campaign_id=campaign.id,
        )
        db.add(delivery)
        db.add(
            OutreachDraftApproval(
                draft_id=draft.id,
                approved_by_user_id=user.id,
                approval_type="email",
                subject=draft.subject,
                body=draft.body,
                experiment_id=draft.experiment_id,
                experiment_variant=draft.experiment_variant,
            )
        )
    db.commit()
    db.refresh(campaign)
    return campaign_out(db, campaign)


@router.post("/email-campaigns/{campaign_id}/{action}", response_model=EmailCampaignOut)
def change_campaign(
    campaign_id: UUID,
    action: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if action not in {"pause", "resume"}:
        raise HTTPException(404, "操作が見つかりません。")
    campaign = db.get(EmailCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "メールキャンペーンが見つかりません。")
    project_access(campaign.project_id, db, user)
    if action == "pause":
        # Keep queued deliveries intact so a paused campaign can be resumed.
        campaign.status = "paused"
    else:
        campaign.status = "queued"
    db.commit()
    db.refresh(campaign)
    return campaign_out(db, campaign)


@router.post("/public/unsubscribe/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    delivery = db.scalar(select(EmailDelivery).where(EmailDelivery.unsubscribe_token == token))
    if delivery is None:
        raise HTTPException(404, "配信情報が見つかりません。")
    company = db.get(Company, delivery.company_id)
    if company is None:
        raise HTTPException(404, "企業情報が見つかりません。")
    company.do_not_contact = True
    company.exclusion_reason = "メールの配信停止リンク"
    db.add(
        SuppressionEntry(
            project_id=company.project_id,
            email=delivery.recipient_email,
            domain=company.domain or "",
            phone=company.phone,
            reason="メールの配信停止リンク",
        )
    )
    db.commit()
    return {"message": "配信を停止しました。"}
