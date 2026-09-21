from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AiReview,
    Company,
    Deal,
    OutreachConversion,
    OutreachDraft,
    OutreachDraftApproval,
    OutreachExperiment,
    OutreachTemplate,
    User,
)
from app.project_access import company_access, project_access
from app.schemas import (
    AiReviewAnalyticsOut,
    AiReviewInput,
    AiReviewOut,
    DealInput,
    DealOut,
    DealPipelineItemOut,
    DealPipelineOut,
    OutreachExperimentAssignmentOut,
    OutreachExperimentInput,
    OutreachExperimentOut,
    OutreachExperimentResultOut,
)
from app.security import current_user

router = APIRouter(prefix="/api")


def owned_experiment(
    experiment_id: UUID, db: Session, user: User, *, write: bool = True
) -> OutreachExperiment:
    experiment = db.get(OutreachExperiment, experiment_id)
    if experiment is None:
        raise HTTPException(404, "A/Bテストが見つかりません。")
    project_access(experiment.project_id, db, user, write=write)
    return experiment


@router.get("/companies/{company_id}/ai-review", response_model=AiReviewOut | None)
def get_ai_review(
    company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company_access(company_id, db, user, write=False)
    return db.scalar(select(AiReview).where(AiReview.company_id == company_id))


@router.put("/companies/{company_id}/ai-review", response_model=AiReviewOut)
def save_ai_review(
    company_id: UUID,
    body: AiReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company_access(company_id, db, user)
    review = db.scalar(select(AiReview).where(AiReview.company_id == company_id))
    if review is None:
        review = AiReview(company_id=company_id, reviewer_id=user.id, **body.model_dump())
        db.add(review)
    else:
        review.reviewer_id = user.id
        review.verdict = body.verdict
        review.note = body.note
    db.commit()
    db.refresh(review)
    return review


@router.get("/projects/{project_id}/ai-review-analytics", response_model=list[AiReviewAnalyticsOut])
def ai_review_analytics(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    reviewed = func.count(AiReview.id)
    correct = func.count(AiReview.id).filter(AiReview.verdict == "correct")
    rows = db.execute(
        select(Company.source_keyword, reviewed, correct)
        .join(AiReview, AiReview.company_id == Company.id)
        .where(Company.project_id == project_id)
        .group_by(Company.source_keyword)
        .order_by(reviewed.desc(), Company.source_keyword)
    ).all()
    return [
        AiReviewAnalyticsOut(
            source_keyword=keyword or "検索語なし",
            reviewed_count=count,
            correct_count=correct_count,
            accuracy_rate=round(correct_count / count * 100, 1) if count else 0,
        )
        for keyword, count, correct_count in rows
    ]


@router.get("/projects/{project_id}/deal-pipeline", response_model=DealPipelineOut)
def deal_pipeline(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    rows = db.execute(
        select(Deal, Company)
        .join(Company, Company.id == Deal.company_id)
        .where(Company.project_id == project_id)
        .order_by(
            Deal.expected_close_date.is_(None), Deal.expected_close_date, Deal.updated_at.desc()
        )
    ).all()
    items = [
        DealPipelineItemOut(
            id=deal.id,
            company_id=deal.company_id,
            project_id=project_id,
            company_name=company.company_name,
            title=deal.title,
            stage=deal.stage,
            expected_amount=deal.expected_amount,
            expected_close_date=deal.expected_close_date,
            owner=deal.owner,
            next_step=deal.next_step,
            lost_reason=deal.lost_reason,
            created_at=deal.created_at,
            updated_at=deal.updated_at,
        )
        for deal, company in rows
    ]
    return DealPipelineOut(
        total_amount=sum(
            item.expected_amount for item in items if item.stage not in {"lost", "won"}
        ),
        by_stage={
            stage: sum(item.stage == stage for item in items)
            for stage in ("lead", "proposal", "negotiation", "won", "lost")
        },
        items=items,
    )


@router.get("/companies/{company_id}/deals", response_model=list[DealOut])
def list_deals(company_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    company_access(company_id, db, user, write=False)
    return db.scalars(
        select(Deal).where(Deal.company_id == company_id).order_by(Deal.updated_at.desc(), Deal.id)
    ).all()


@router.post("/companies/{company_id}/deals", response_model=DealOut, status_code=201)
def create_deal(
    company_id: UUID,
    body: DealInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company_access(company_id, db, user)
    deal = Deal(company_id=company_id, **body.model_dump())
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


@router.put("/deals/{deal_id}", response_model=DealOut)
def update_deal(
    deal_id: UUID,
    body: DealInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "案件が見つかりません。")
    company_access(deal.company_id, db, user)
    for key, value in body.model_dump().items():
        setattr(deal, key, value)
    db.commit()
    db.refresh(deal)
    return deal


@router.delete("/deals/{deal_id}", status_code=204)
def delete_deal(deal_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "案件が見つかりません。")
    company_access(deal.company_id, db, user)
    db.delete(deal)
    db.commit()


@router.get(
    "/projects/{project_id}/outreach-experiments", response_model=list[OutreachExperimentOut]
)
def list_experiments(
    project_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    project_access(project_id, db, user, write=False)
    return db.scalars(
        select(OutreachExperiment)
        .where(OutreachExperiment.project_id == project_id)
        .order_by(OutreachExperiment.created_at.desc())
    ).all()


@router.post(
    "/projects/{project_id}/outreach-experiments",
    response_model=OutreachExperimentOut,
    status_code=201,
)
def create_experiment(
    project_id: UUID,
    body: OutreachExperimentInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    templates = db.scalars(
        select(OutreachTemplate).where(
            OutreachTemplate.id.in_((body.template_a_id, body.template_b_id))
        )
    ).all()
    if len(templates) != 2 or any(template.project_id != project_id for template in templates):
        raise HTTPException(422, "同じプロジェクトの異なる文面テンプレートを2つ選択してください。")
    if templates[0].channel != templates[1].channel:
        raise HTTPException(422, "A/Bテストの文面種別をそろえてください。")
    experiment = OutreachExperiment(project_id=project_id, **body.model_dump())
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return experiment


@router.post(
    "/outreach-experiments/{experiment_id}/apply/{draft_id}",
    response_model=OutreachExperimentAssignmentOut,
)
def apply_experiment(
    experiment_id: UUID,
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    experiment = owned_experiment(experiment_id, db, user)
    if not experiment.active:
        raise HTTPException(409, "このA/Bテストは停止中です。")
    draft = db.get(OutreachDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "営業文面が見つかりません。")
    company = company_access(draft.company_id, db, user)
    if company.project_id != experiment.project_id:
        raise HTTPException(422, "対象企業がA/Bテストのプロジェクトに含まれていません。")
    variant = "A" if company.id.int % 2 == 0 else "B"
    template = db.get(
        OutreachTemplate, experiment.template_a_id if variant == "A" else experiment.template_b_id
    )
    if template is None or template.channel != draft.channel:
        raise HTTPException(422, "文面種別が対象の営業文面と一致しません。")
    draft.subject = template.subject
    draft.body = template.body
    draft.experiment_id = experiment.id
    draft.experiment_variant = variant
    db.commit()
    return OutreachExperimentAssignmentOut(
        experiment_id=experiment.id, variant=variant, template=template
    )


@router.get(
    "/outreach-experiments/{experiment_id}/results",
    response_model=list[OutreachExperimentResultOut],
)
def experiment_results(
    experiment_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    experiment = owned_experiment(experiment_id, db, user, write=False)
    delivered = func.count(OutreachDraftApproval.id)
    replied = func.count(func.distinct(OutreachConversion.approval_id)).filter(
        OutreachConversion.outcome == "replied"
    )
    meetings = func.count(func.distinct(OutreachConversion.approval_id)).filter(
        OutreachConversion.outcome == "meeting"
    )
    won = func.count(func.distinct(OutreachConversion.approval_id)).filter(
        OutreachConversion.outcome == "won"
    )
    rows = db.execute(
        select(OutreachDraftApproval.experiment_variant, delivered, replied, meetings, won)
        .outerjoin(OutreachConversion, OutreachConversion.approval_id == OutreachDraftApproval.id)
        .where(
            OutreachDraftApproval.experiment_id == experiment.id,
            OutreachDraftApproval.delivered_at.is_not(None),
        )
        .group_by(OutreachDraftApproval.experiment_variant)
    ).all()
    values = {
        variant: (count, replies, meeting_count, won_count)
        for variant, count, replies, meeting_count, won_count in rows
    }
    return [
        OutreachExperimentResultOut(
            variant=variant,
            delivered=values.get(variant, (0, 0, 0, 0))[0],
            replied=values.get(variant, (0, 0, 0, 0))[1],
            meetings=values.get(variant, (0, 0, 0, 0))[2],
            won=values.get(variant, (0, 0, 0, 0))[3],
            reply_rate=round(
                values.get(variant, (0, 0, 0, 0))[1] / values.get(variant, (0, 0, 0, 0))[0] * 100, 1
            )
            if values.get(variant, (0, 0, 0, 0))[0]
            else 0,
        )
        for variant in ("A", "B")
    ]
