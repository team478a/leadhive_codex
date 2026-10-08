"""A2 REST boundary. None of these routes send, enqueue or consume deliveries."""

import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.model_approval import (
    AgentCredential,
    AgentIdentity,
    AgentProjectGrant,
    ApprovalRequest,
    OutreachAuditEvent,
)
from app.models import (
    CF7Observation,
    Company,
    FormProfile,
    FormProfileField,
    FormSenderSettings,
    OutreachDraft,
    Project,
    ProjectMember,
    User,
)
from app.project_access import company_access, project_access
from app.schema_approval import (
    AgentIssue,
    Approve,
    ChallengeVerify,
    Decision,
    ExpectedPayload,
    FormPreparation,
    Proposal,
    Revision,
)
from app.security import COOKIE_NAME, current_user, token_digest
from app.services import human_approval as service
from app.services.approval_principals import authenticate_agent
from app.services.form_adapter_preparation import adapter_preparation
from app.services.form_adapter_preparation import enabled as adapter_enabled
from app.services.form_approval_preparation import preparation

router = APIRouter(prefix="/api", tags=["Human Approval Foundation A2"])


def request_item(db, request_id):
    item = db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
    )
    if not item:
        raise HTTPException(404, "提案が見つかりません。")
    return item


def human_item(db, request_id, user, write=True, owner=False):
    item = db.get(ApprovalRequest, request_id)
    if not item:
        raise HTTPException(404, "提案が見つかりません。")
    # Lock authorization rows for the decision transaction (not just the UI role).
    db.scalar(select(Project).where(Project.id == item.project_id).with_for_update())
    db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == item.project_id, ProjectMember.user_id == user.id)
        .with_for_update()
    )
    project_access(item.project_id, db, user, write=write, owner=owner)
    item = request_item(db, request_id)
    if (
        item.delivery_method
        in {"cf7_candidate_only", "cf7_real_candidate_only", "cf7_real_reservation"}
        and write
    ):
        lock_preparation_sources(db, db.get(Company, item.company_id), user)
    return item


def serialize(db, item):
    company = db.get(Company, item.company_id)
    result = {c.name: getattr(item, c.name) for c in ApprovalRequest.__table__.columns}
    result["company_name"] = company.company_name if company else ""
    result["lead_dm_evidence"] = item.payload_snapshot.get("lead_dm_binding")
    result["form_action_url"] = item.payload_snapshot.get("form_action_url")
    result["execution_plan"] = item.payload_snapshot.get("execution_plan")
    result["execution_plan_hash"] = item.payload_snapshot.get("execution_plan_hash")
    result["adapter_plan"] = item.payload_snapshot.get("adapter_plan")
    result["adapter_plan_hash"] = item.payload_snapshot.get("adapter_plan_hash")
    result["cf7_reservation_plan"] = item.payload_snapshot.get("cf7_reservation_plan")
    result["cf7_real_handoff"] = item.payload_snapshot.get("cf7_real_handoff")
    if item.delivery_method == "cf7_candidate_only":
        result["cf7_candidate_snapshot"] = item.payload_snapshot.get("cf7_candidate_snapshot")
        result["cf7_candidate_snapshot_hash"] = item.payload_snapshot.get(
            "cf7_candidate_snapshot_hash"
        )
        observation = db.get(CF7Observation, item.payload_snapshot.get("cf7_observation_id"))
        result["cf7_observation"] = (
            {
                "observed_at": observation.observed_at,
                "expires_at": observation.expires_at,
                "evidence_hash": observation.evidence_hash,
            }
            if observation
            else None
        )
    return result


def preparation_source(db, draft_id, user):
    draft = db.get(OutreachDraft, draft_id)
    if not draft:
        raise HTTPException(404, "Draftが見つかりません。")
    company = company_access(draft.company_id, db, user)
    return company, draft


@router.get("/outreach-drafts/{draft_id}/form-approval-preview")
def preview_form_approval(
    draft_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company, draft = preparation_source(db, draft_id, user)
    return preparation(db, company, draft)[1]


@router.post("/outreach-drafts/{draft_id}/form-approval-request", status_code=201)
def prepare_form_approval(
    draft_id: UUID,
    body: FormPreparation,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company, draft = preparation_source(db, draft_id, user)
    lock_preparation_sources(db, company, user)
    proposal, preview = preparation(db, company, draft)
    if preview["preparation_hash"] != body.expected_preparation_hash:
        raise HTTPException(409, "準備内容が変更されています。もう一度内容を取得してください。")
    return serialize(
        db, service.create_proposal(db, company.project_id, proposal, "HUMAN", user.id)
    )


def lock_preparation_sources(db, company, user):
    db.scalar(select(Project).where(Project.id == company.project_id).with_for_update())
    db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == company.project_id, ProjectMember.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    project_access(company.project_id, db, user)
    # Keep the reviewed source data stable until the proposal and ledger commit.
    db.scalar(
        select(Company)
        .where(Company.id == company.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    db.scalars(
        select(OutreachDraft)
        .where(OutreachDraft.company_id == company.id)
        .order_by(OutreachDraft.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    db.scalar(
        select(FormSenderSettings)
        .where(FormSenderSettings.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    db.scalars(
        select(FormProfile)
        .where(FormProfile.company_id == company.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    db.scalars(
        select(FormProfileField)
        .where(
            FormProfileField.form_profile_id.in_(
                select(FormProfile.id).where(FormProfile.company_id == company.id)
            )
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()


@router.get("/form-adapter-preparation-status")
def adapter_status(user: User = Depends(current_user)):
    return {"enabled": adapter_enabled(), "reservation_only": True}


@router.get("/outreach-drafts/{draft_id}/form-adapter-preview")
def preview_form_adapter(
    draft_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    company, draft = preparation_source(db, draft_id, user)
    return adapter_preparation(db, company, draft)[1]


@router.post("/outreach-drafts/{draft_id}/form-adapter-request", status_code=201)
def prepare_form_adapter(
    draft_id: UUID,
    body: FormPreparation,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company, draft = preparation_source(db, draft_id, user)
    lock_preparation_sources(db, company, user)
    proposal, preview = adapter_preparation(db, company, draft)
    if preview["preparation_hash"] != body.expected_preparation_hash:
        raise HTTPException(409, "準備内容が変更されています。もう一度内容を取得してください。")
    return serialize(
        db,
        service.create_proposal(
            db, company.project_id, proposal, "HUMAN", user.id, allow_adapter_preparation=True
        ),
    )


def list_items(db, project_id, status, limit, offset):
    # Validate the displayed page; dispatch and every decision also validate independently.
    query = select(ApprovalRequest).where(ApprovalRequest.project_id == project_id)
    if status:
        query = query.where(ApprovalRequest.status == status)
    items = db.scalars(
        query.order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id)
        .limit(limit)
        .offset(offset)
        .with_for_update()
    ).all()
    for item in items:
        service.invalidate_if_needed(db, item)
    db.commit()
    return [serialize(db, item) for item in items]


@router.post("/projects/{project_id}/agents", status_code=201)
def issue_agent(
    project_id: UUID,
    body: AgentIssue,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, owner=True)
    identity = AgentIdentity(name=body.name, created_by_user_id=user.id)
    db.add(identity)
    db.flush()
    token = "lh_agent_" + secrets.token_urlsafe(32)
    credential = AgentCredential(
        agent_id=identity.id,
        token_hash=token_digest(token),
        scopes=body.scopes,
        expires_at=service.now() + timedelta(days=body.expires_in_days),
    )
    db.add_all(
        [
            credential,
            AgentProjectGrant(agent_id=identity.id, project_id=project_id, scopes=body.scopes),
        ]
    )
    db.add(
        OutreachAuditEvent(
            event="credential issued",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            reason="agent credential issued",
        )
    )
    db.commit()
    # Secret is returned once; never stored in the ledger or exposed by read APIs.
    return {
        "agent_id": identity.id,
        "credential_id": credential.id,
        "token": token,
        "scopes": body.scopes,
        "expires_at": credential.expires_at,
    }


@router.post("/projects/{project_id}/agents/{agent_id}/revoke")
def revoke_agent(
    project_id: UUID,
    agent_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, owner=True)
    grant = db.scalar(
        select(AgentProjectGrant)
        .where(AgentProjectGrant.agent_id == agent_id, AgentProjectGrant.project_id == project_id)
        .with_for_update()
    )
    if not grant:
        raise HTTPException(404, "Agentが見つかりません。")
    grant.active = False
    db.add(
        OutreachAuditEvent(
            event="grant revoked",
            principal_type="HUMAN",
            actor_id=user.id,
            project_id=project_id,
            reason="agent project grant revoked",
        )
    )
    db.commit()
    return {"revoked": True}


@router.post("/projects/{project_id}/approval-requests", status_code=201)
def create_human(
    project_id: UUID,
    body: Proposal,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user)
    return serialize(db, service.create_proposal(db, project_id, body, "HUMAN", user.id))


@router.get("/projects/{project_id}/approval-requests")
def list_human(
    project_id: UUID,
    status: str | None = Query(
        default=None, pattern="^(PENDING|APPROVED|REJECTED|EXPIRED|REVOKED|CONSUMED)$"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    return list_items(db, project_id, status, limit, offset)


@router.get("/approval-requests/{request_id}")
def read_human(request_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = human_item(db, request_id, user, write=False)
    service.invalidate_if_needed(db, item)
    db.commit()
    return serialize(db, item)


@router.post("/approval-requests/{request_id}/revisions", status_code=201)
def revise(
    request_id: UUID,
    body: Revision,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    previous = human_item(db, request_id, user)
    service.expected(previous, body)
    service.invalidate_if_needed(db, previous)
    return serialize(
        db, service.create_proposal(db, previous.project_id, body, "HUMAN", user.id, previous)
    )


@router.post("/approval-requests/{request_id}/challenge")
def create_challenge(
    request_id: UUID,
    body: ExpectedPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return service.challenge(
        db, human_item(db, request_id, user), body, user, token_digest(request.cookies[COOKIE_NAME])
    )


@router.post("/approval-requests/{request_id}/challenge/verify")
def verify_challenge(
    request_id: UUID,
    body: ChallengeVerify,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return service.verify_challenge(
        db, human_item(db, request_id, user), body, user, token_digest(request.cookies[COOKIE_NAME])
    )


@router.post("/approval-requests/{request_id}/approve")
def approve(
    request_id: UUID,
    body: Approve,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return serialize(
        db,
        service.approve(
            db,
            human_item(db, request_id, user),
            body,
            user,
            token_digest(request.cookies[COOKIE_NAME]),
        ),
    )


@router.post("/approval-requests/{request_id}/reject")
def reject(
    request_id: UUID,
    body: Decision,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return serialize(
        db, service.decide(db, human_item(db, request_id, user), body, user, "REJECTED")
    )


@router.post("/approval-requests/{request_id}/revoke")
def revoke(
    request_id: UUID,
    body: Decision,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return serialize(
        db, service.decide(db, human_item(db, request_id, user), body, user, "REVOKED")
    )


@router.get("/projects/{project_id}/approval-audit")
def ledger(
    project_id: UUID,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    rows = db.scalars(
        select(OutreachAuditEvent)
        .where(OutreachAuditEvent.project_id == project_id)
        .order_by(OutreachAuditEvent.timestamp.desc(), OutreachAuditEvent.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        {c.name: getattr(row, c.name) for c in OutreachAuditEvent.__table__.columns} for row in rows
    ]


@router.post("/agent/projects/{project_id}/approval-requests", status_code=201)
def create_agent(project_id: UUID, body: Proposal, request: Request, db: Session = Depends(get_db)):
    agent = authenticate_agent(request, db, project_id, "outreach:prepare")
    return serialize(db, service.create_proposal(db, project_id, body, "AGENT", agent.id))


@router.get("/agent/projects/{project_id}/approval-requests")
def read_agent(
    project_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    authenticate_agent(request, db, project_id, "outreach:read")
    return list_items(db, project_id, None, limit, offset)


@router.post(
    "/agent/projects/{project_id}/approval-requests/{request_id}/revisions", status_code=201
)
def revise_agent(
    project_id: UUID,
    request_id: UUID,
    body: Revision,
    request: Request,
    db: Session = Depends(get_db),
):
    agent = authenticate_agent(request, db, project_id, "outreach:prepare")
    previous = request_item(db, request_id)
    if previous.project_id != project_id:
        raise HTTPException(404, "提案が見つかりません。")
    service.expected(previous, body)
    service.invalidate_if_needed(db, previous)
    return serialize(db, service.create_proposal(db, project_id, body, "AGENT", agent.id, previous))


@router.get("/approval-requests/{request_id}/cf7-reservation-preview")
def cf7_reservation_preview(
    request_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    from app.services import cf7_real_reservation

    item = human_item(db, request_id, user, write=False)
    try:
        result = cf7_real_reservation.preview(db, item)
    except HTTPException:
        db.commit()
        raise
    db.commit()
    return result


@router.post("/approval-requests/{request_id}/cf7-reservation-request", status_code=201)
def cf7_reservation_request(
    request_id: UUID,
    body: FormPreparation,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    from app.services import cf7_real_reservation

    item = human_item(db, request_id, user)
    try:
        return serialize(
            db, cf7_real_reservation.create_request(db, item, user, body.expected_preparation_hash)
        )
    except HTTPException:
        db.commit()
        raise
