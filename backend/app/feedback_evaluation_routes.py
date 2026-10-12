"""Admin-owner aggregate evaluation history. No AI, rule application or delivery."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.feedback_export_routes import export_feedback
from app.feedback_review_routes import guard
from app.models import FeedbackEvaluation, FeedbackEvaluationNote, Project, User
from app.security import current_admin
from offline_replay.comparison import digest
from offline_replay.evaluation_history import checkpoint, trend

router = APIRouter(prefix="/api/projects")


def output(db, row):
    notes = list(
        db.scalars(
            select(FeedbackEvaluationNote)
            .where(FeedbackEvaluationNote.evaluation_id == row.id)
            .order_by(FeedbackEvaluationNote.version)
        )
    )
    return {
        "id": row.id,
        "project_id": row.project_id,
        "report": row.report,
        "comparison": row.comparison,
        "previous_id": row.previous_id,
        "created_at": row.created_at,
        "created_by": row.created_by,
        "version": notes[-1].version if notes else 0,
        "notes": [
            {
                "version": n.version,
                "reason": n.reason,
                "note": n.note,
                "actor_id": n.actor_id,
                "created_at": n.created_at,
                "principal_verified": True,
                "classification": "OPERATOR_EXPLANATION",
            }
            for n in notes
        ],
        "runtime_applied": False,
        "execution_allowed": False,
    }


@router.get("/{project_id}/feedback-evaluations")
def list_evaluations(
    project_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    guard(project_id, db, user)
    rows = list(
        db.scalars(
            select(FeedbackEvaluation)
            .where(FeedbackEvaluation.project_id == project_id)
            .order_by(FeedbackEvaluation.created_at.desc(), FeedbackEvaluation.id)
            .limit(101)
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return {"items": [output(db, r) for r in rows[:100]], "truncated": len(rows) > 100}


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: AwareDatetime
    end: AwareDatetime
    previous_id: UUID | None = None


@router.post("/{project_id}/feedback-evaluations")
def save_evaluation(
    project_id: UUID,
    body: EvaluationInput,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    guard(project_id, db, user)
    if body.start >= body.end:
        raise HTTPException(422, "終了日時は開始日時より後にしてください。")
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    previous = None
    if body.previous_id:
        previous = db.scalar(
            select(FeedbackEvaluation).where(
                FeedbackEvaluation.id == body.previous_id,
                FeedbackEvaluation.project_id == project_id,
            )
        )
        if previous is None:
            raise HTTPException(404, "比較する評価履歴が見つかりません。")
    source = export_feedback(project_id, Response(), db, user, start=body.start, end=body.end)
    try:
        report = checkpoint(
            source, str(project_id), start=body.start.isoformat(), end=body.end.isoformat()
        )
        comparison = trend(previous.report, report) if previous else None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, "評価の出所・期間・比較履歴を確認してください。") from None
    key = digest(
        [
            report["input_hash"],
            report["period"],
            str(body.previous_id),
            report["schema_version"],
            report["metric_definition"],
        ]
    )
    row = db.scalar(
        select(FeedbackEvaluation).where(
            FeedbackEvaluation.project_id == project_id,
            FeedbackEvaluation.record_key == key,
        )
    )
    if row is None:
        row = FeedbackEvaluation(
            project_id=project_id,
            record_key=key,
            report=report,
            comparison=comparison,
            previous_id=body.previous_id,
            created_by=user.id,
        )
        db.add(row)
        db.flush()
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return output(db, row)


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    reason: Literal[
        "INSUFFICIENT_EVALUATION",
        "COHORT_CHANGED",
        "NO_MEASURED_GAIN",
        "REGRESSION",
        "NOT_APPLIED",
        "OTHER",
    ]
    note: str = Field(min_length=1, max_length=2000)


@router.post("/{project_id}/feedback-evaluations/{evaluation_id}/notes")
def save_note(
    project_id: UUID,
    evaluation_id: UUID,
    body: NoteInput,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    guard(project_id, db, user)
    row = db.scalar(
        select(FeedbackEvaluation)
        .where(
            FeedbackEvaluation.id == evaluation_id,
            FeedbackEvaluation.project_id == project_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "評価履歴が見つかりません。")
    if output(db, row)["version"] != body.expected_version:
        raise HTTPException(409, "理由が更新されています。再読み込みしてください。")
    if not body.note.strip():
        raise HTTPException(422, "理由の説明を入力してください。")
    db.add(
        FeedbackEvaluationNote(
            evaluation_id=row.id,
            version=body.expected_version + 1,
            reason=body.reason,
            note=body.note.strip(),
            actor_id=user.id,
        )
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return output(db, row)
