"""Human admin research decisions. No runtime rules, AI requests or delivery calls."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.feedback_export_routes import export_feedback
from app.models import FeedbackProposal, FeedbackProposalDecision, Project, User
from app.project_access import project_access
from app.security import current_admin
from offline_replay.improvement import workbench

router = APIRouter(prefix="/api/projects")


def guard(project_id, db, user):
    if not settings.feedback_workbench_enabled:
        raise HTTPException(404, "改善候補の確認は現在無効です。")
    return project_access(project_id, db, user, write=False, owner=True)


def history(db, proposal):
    return list(
        db.scalars(
            select(FeedbackProposalDecision)
            .where(FeedbackProposalDecision.proposal_id == proposal.id)
            .order_by(FeedbackProposalDecision.version)
        )
    )


def output(db, proposal):
    rows = history(db, proposal)
    return {
        "id": proposal.id,
        "project_id": proposal.project_id,
        "input_hash": proposal.input_hash,
        "report": proposal.report,
        "created_at": proposal.created_at,
        "created_by": proposal.created_by,
        "version": rows[-1].version if rows else 0,
        "state": rows[-1].state if rows else "PROPOSED",
        "history": [
            {
                "version": r.version,
                "state": r.state,
                "reason": r.reason,
                "actor_id": r.actor_id,
                "created_at": r.created_at,
                "restored_from": r.restored_from,
            }
            for r in rows
        ],
        "runtime_applied": False,
        "execution_allowed": False,
    }


@router.get("/{project_id}/feedback-proposals")
def list_proposals(
    project_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    guard(project_id, db, user)
    response.headers["Cache-Control"] = "no-store"
    rows = list(
        db.scalars(
            select(FeedbackProposal)
            .where(FeedbackProposal.project_id == project_id)
            .order_by(FeedbackProposal.created_at.desc(), FeedbackProposal.id)
            .limit(101)
        )
    )
    return {"items": [output(db, r) for r in rows[:100]], "truncated": len(rows) > 100}


@router.post("/{project_id}/feedback-proposals/analyze")
def analyze_saved(
    project_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    guard(project_id, db, user)
    # Serializes concurrent analysis/import without mutating Project itself.
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    source = export_feedback(project_id, Response(), db, user)
    try:
        report = workbench(source, str(project_id))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            409, "保存済み評価を比較できません。出所と元判定を確認してください。"
        ) from None
    ids = []
    for comparison in report["comparisons"]:
        key = comparison["proposal"]["id"]
        proposal = db.scalar(
            select(FeedbackProposal).where(
                FeedbackProposal.project_id == project_id,
                FeedbackProposal.input_hash == report["input_hash"],
                FeedbackProposal.proposal_key == key,
            )
        )
        if proposal is None:
            proposal = FeedbackProposal(
                project_id=project_id,
                input_hash=report["input_hash"],
                proposal_key=key,
                created_by=user.id,
                report={
                    "schema_version": report["schema_version"],
                    "dataset_kind": report["dataset_kind"],
                    "comparison": comparison,
                    "development_analysis": report["development_analysis"],
                    "sealed_evaluation_certified": False,
                    "estimated_api_cost": None,
                },
            )
            db.add(proposal)
            db.flush()
        ids.append(proposal.id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {
        "proposal_ids": ids,
        "event_count": report["event_count"],
        "unresolved_samples": report["development_analysis"]["unresolved_samples"],
        "api_calls": 0,
        "runtime_applied": False,
    }


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    state: Literal["ACCEPTED", "REJECTED", "DEFERRED"]
    reason: str = Field(min_length=1, max_length=2000)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    restore_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


def locked(project_id, proposal_id, db, user, expected):
    guard(project_id, db, user)
    proposal = db.scalar(
        select(FeedbackProposal)
        .where(FeedbackProposal.project_id == project_id, FeedbackProposal.id == proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise HTTPException(404, "改善候補が見つかりません。")
    rows = history(db, proposal)
    if (rows[-1].version if rows else 0) != expected:
        raise HTTPException(409, "他の操作で判断が更新されました。再読み込みしてください。")
    return proposal, rows


def record_decision(db, proposal, user, expected, state, reason, restored=None):
    if not reason.strip():
        raise HTTPException(422, "判断理由を入力してください。")
    if state == "ACCEPTED" and proposal.report["comparison"]["regressions"]:
        raise HTTPException(409, "回帰がある改善候補は採用できません。")
    db.add(
        FeedbackProposalDecision(
            proposal_id=proposal.id,
            version=expected + 1,
            actor_id=user.id,
            state=state,
            reason=reason.strip(),
            restored_from=restored,
        )
    )
    db.commit()
    return output(db, proposal)


@router.post("/{project_id}/feedback-proposals/{proposal_id}/decisions")
def decide(
    project_id: UUID,
    proposal_id: UUID,
    body: DecisionInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    proposal, _ = locked(project_id, proposal_id, db, user, body.expected_version)
    return record_decision(db, proposal, user, body.expected_version, body.state, body.reason)


@router.post("/{project_id}/feedback-proposals/{proposal_id}/restore")
def restore(
    project_id: UUID,
    proposal_id: UUID,
    body: RestoreInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    proposal, rows = locked(project_id, proposal_id, db, user, body.expected_version)
    prior = next((r for r in rows if r.version == body.restore_version), None)
    if prior is None:
        raise HTTPException(404, "復元する判断版が見つかりません。")
    return record_decision(
        db, proposal, user, body.expected_version, prior.state, body.reason, prior.version
    )
