"""Human Pair truth on immutable observations; no training or Company merge."""

from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    RawLeadReview,
    RawLeadSnapshot,
    RawPairReview,
    RawQueryRun,
    RawReviewSession,
    User,
)
from app.raw_collection_routes import access, observation
from app.security import current_user
from app.services.contact_destinations import normalize_destination
from app.services.raw_benchmark import digest
from app.services.raw_repeat import pair_features

router = APIRouter(prefix="/api/raw-benchmarks")


def pair(db, user, left_id, right_id, *, write=False):
    if left_id == right_id:
        raise HTTPException(422, "異なる2候補を指定してください。")
    left_id, right_id = sorted((left_id, right_id))
    left, right = db.get(RawLeadSnapshot, left_id), db.get(RawLeadSnapshot, right_id)
    if not left or not right:
        raise HTTPException(404, "候補が見つかりません。")
    a, b = db.get(RawQueryRun, left.run_id), db.get(RawQueryRun, right.run_id)
    access(db, user, a.benchmark_id, write=write)
    if a.benchmark_id != b.benchmark_id:
        raise HTTPException(404, "同じBenchmarkの候補を指定してください。")
    if write:
        observation(db, user, left_id)
    features = pair_features(left, right)
    previous = db.scalar(
        select(RawPairReview)
        .where(RawPairReview.left_id == left_id, RawPairReview.right_id == right_id)
        .order_by(RawPairReview.version.desc())
        .limit(1)
    )
    return left, right, features, digest(features), previous


@router.get("/pairs/{left_id}/{right_id}")
def preview(
    left_id: UUID, right_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    left, right, features, hash_value, previous = pair(db, user, left_id, right_id)
    return {
        "left_id": left.id,
        "right_id": right.id,
        "pair_hash": hash_value,
        "features": features,
        "version": previous.version if previous else 0,
        "outcome": previous.outcome if previous else None,
    }


class PairInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: UUID
    pair_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_version: int = Field(ge=0)
    outcome: str
    reason: str = Field(min_length=2, max_length=1000)
    evidence_url: str = Field(min_length=1, max_length=2048)


@router.post("/pairs/{left_id}/{right_id}/reviews", status_code=201)
def review(
    left_id: UUID,
    right_id: UUID,
    body: PairInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    left, right, features, hash_value, previous = pair(db, user, left_id, right_id, write=True)
    if body.pair_hash != hash_value or body.expected_version != (
        previous.version if previous else 0
    ):
        raise HTTPException(409, "Pair根拠または版が変わりました。")
    if body.outcome not in {"SAME", "DIFFERENT", "UNSURE"}:
        raise HTTPException(422, "Pair判定が正しくありません。")
    session = db.get(RawReviewSession, body.session_id)
    now = datetime.now(timezone.utc)
    if (
        not session
        or session.user_id != user.id
        or session.snapshot_id != left.id
        or session.snapshot_hash != left.snapshot_hash
        or session.finished_at
        or not 0 <= (now - session.started_at).total_seconds() <= 14400
        or db.scalar(select(RawLeadReview.id).where(RawLeadReview.session_id == body.session_id))
    ):
        raise HTTPException(409, "確認開始記録が無効・使用済み・失効しています。")
    try:
        parsed = urlsplit(body.evidence_url)
        evidence = normalize_destination("form", body.evidence_url)
        if parsed.query or parsed.fragment:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPException(422, "根拠は秘密情報のない公開URLを指定してください。") from None
    row = RawPairReview(
        left_id=left.id,
        right_id=right.id,
        session_id=session.id,
        reviewer_id=user.id,
        version=body.expected_version + 1,
        pair_hash=hash_value,
        features=features,
        outcome=body.outcome,
        reason=body.reason,
        evidence_url=evidence,
        duration_seconds=int((now - session.started_at).total_seconds()),
        reviewed_at=now,
    )
    session.finished_at = now
    db.add(row)
    db.commit()
    return {
        "version": row.version,
        "outcome": row.outcome,
        "reviewer": row.reviewer_id,
        "duration_seconds": row.duration_seconds,
    }
