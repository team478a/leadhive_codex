"""Human-only bulk approval and reservation boundary."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approval_routes import serialize
from app.database import get_db
from app.model_approved_email import ApprovedEmailBatch, ApprovedEmailReservation
from app.models import (
    ApprovalRequest,
    Company,
    EmailDelivery,
    OutreachAuditEvent,
    OutreachDraft,
    Project,
    ProjectMember,
    User,
)
from app.project_access import project_access
from app.schema_approval import ChallengeVerify, Proposal, Sender
from app.schema_approved_email import (
    ApprovedBatchCreate,
    BulkApprove,
    BulkSelection,
    DraftSelection,
)
from app.security import COOKIE_NAME, current_user, token_digest
from app.services import approved_email, bulk_approval, human_approval
from app.services.email_delivery import smtp_configuration

router = APIRouter(prefix="/api", tags=["Human approved email"])


def access(db, project_id, user, write=True):
    if write:
        db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        db.scalar(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id)
            .with_for_update()
        )
    return project_access(project_id, db, user, write=write)


@router.post("/projects/{project_id}/bulk-approval/challenge")
def challenge(
    project_id: UUID,
    body: BulkSelection,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user)
    return bulk_approval.challenge(
        db, project_id, body, user, token_digest(request.cookies[COOKIE_NAME])
    )


@router.post("/projects/{project_id}/bulk-approval/verify")
def verify(
    project_id: UUID,
    body: ChallengeVerify,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user)
    return bulk_approval.verify(
        db, project_id, body, user, token_digest(request.cookies[COOKIE_NAME])
    )


@router.post("/projects/{project_id}/bulk-approval/approve")
def approve(
    project_id: UUID,
    body: BulkApprove,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user)
    return bulk_approval.approve(
        db, project_id, body, user, token_digest(request.cookies[COOKIE_NAME])
    )


@router.get("/projects/{project_id}/approval-email-drafts")
def drafts(
    project_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user, False)
    rows = db.execute(
        select(OutreachDraft, Company.company_name, Company.email)
        .join(Company, Company.id == OutreachDraft.company_id)
        .where(
            Company.project_id == project_id,
            OutreachDraft.channel == "email",
            ~OutreachDraft.id.in_(
                select(ApprovalRequest.source_draft_id).where(
                    ApprovalRequest.source_draft_id.is_not(None),
                    ApprovalRequest.status.in_(("PENDING", "APPROVED", "CONSUMED")),
                )
            ),
        )
        .order_by(OutreachDraft.created_at.desc(), OutreachDraft.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {"id": d.id, "company_name": name, "recipient": email, "subject": d.subject, "body": d.body}
        for d, name, email in rows
    ]


@router.post("/projects/{project_id}/approval-requests/from-drafts", status_code=201)
def from_drafts(
    project_id: UUID,
    body: DraftSelection,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user)
    config = smtp_configuration(db)
    if not config.from_name or not config.from_email:
        raise HTTPException(409, "SMTP送信者名とメールアドレスを設定してください。")
    proposals = []
    for draft_id in body.draft_ids:
        draft = db.get(OutreachDraft, draft_id)
        company = db.get(Company, draft.company_id) if draft else None
        if not company or company.project_id != project_id:
            raise HTTPException(404, "文面が見つかりません。")
        if draft.channel != "email" or not company.email or not draft.body.strip():
            raise HTTPException(409, "宛先とメール文面が必要です。")
        if db.scalar(
            select(ApprovalRequest.id)
            .where(
                ApprovalRequest.source_draft_id == draft.id,
                ApprovalRequest.status.in_(("PENDING", "APPROVED", "CONSUMED")),
            )
            .limit(1)
        ):
            raise HTTPException(409, "この文面は既に承認提案になっています。")
        proposals.append(
            Proposal(
                company_id=company.id,
                channel="email",
                delivery_method="email",
                source_draft_id=draft.id,
                recipient=company.email,
                subject=draft.subject,
                body=draft.body,
                sender=Sender(name=config.from_name, email=config.from_email),
            )
        )
    items = [
        human_approval.create_proposal(db, project_id, p, "HUMAN", user.id, commit=False)
        for p in proposals
    ]
    db.commit()
    return [serialize(db, i) for i in items]


@router.post("/projects/{project_id}/approved-email-batches", status_code=201)
def create_batch(
    project_id: UUID,
    body: ApprovedBatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user)
    batch = approved_email.create_batch(db, project_id, body, user)
    return approved_email.batch_summary(db, batch)


@router.get("/projects/{project_id}/approved-email-batches")
def list_batches(
    project_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    access(db, project_id, user, False)
    approved_email.expire_queued(db)
    batches = db.scalars(
        select(ApprovedEmailBatch)
        .where(ApprovedEmailBatch.project_id == project_id)
        .order_by(ApprovedEmailBatch.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    results = [approved_email.batch_summary(db, b) for b in batches]
    db.commit()
    return results


@router.post("/approved-email-batches/{batch_id}/{action}")
def change_batch(
    batch_id: UUID, action: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    batch = db.get(ApprovedEmailBatch, batch_id)
    if not batch:
        raise HTTPException(404, "予約が見つかりません。")
    access(db, batch.project_id, user)
    from sqlalchemy import func

    db.execute(select(func.pg_advisory_xact_lock(approved_email.RESERVATION_LOCK)))
    batch = db.scalar(
        select(ApprovedEmailBatch)
        .where(ApprovedEmailBatch.id == batch_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if action not in {"pause", "resume", "cancel"} or batch.status not in {"queued", "paused"}:
        raise HTTPException(409, "この状態から変更できません。")
    batch.status = {"pause": "paused", "resume": "queued", "cancel": "cancelled"}[action]
    if action == "cancel":
        rows = db.scalars(
            select(EmailDelivery)
            .join(
                ApprovedEmailReservation, ApprovedEmailReservation.delivery_id == EmailDelivery.id
            )
            .where(ApprovedEmailReservation.batch_id == batch.id, EmailDelivery.status == "queued")
            .with_for_update(of=EmailDelivery)
        ).all()
        for delivery in rows:
            delivery.status, delivery.finished_at = "cancelled", human_approval.now()
    db.add(
        OutreachAuditEvent(
            event="email batch " + action,
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=batch.project_id,
            reason=str(batch.id),
        )
    )
    db.commit()
    return approved_email.batch_summary(db, batch)
