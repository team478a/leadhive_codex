"""Human-only, bounded discovery Pilot. No Company ingestion or downstream jobs."""

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    Project,
    RawBenchmark,
    RawLeadReview,
    RawLeadSnapshot,
    RawPairReview,
    RawQueryRun,
    RawReviewSession,
    TargetProfile,
    User,
)
from app.project_access import accessible_project_condition, project_access
from app.security import current_user
from app.services.collection import ExternalServiceError, search_gbizinfo, search_serper
from app.services.contact_destinations import normalize_destination
from app.services.raw_benchmark import OUTCOMES, commit_id, digest, latest_review, report
from app.services.raw_capture import capturing

router = APIRouter(prefix="/api/raw-benchmarks")


class CreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    region: str = Field(min_length=1, max_length=500)
    industry: str = Field(min_length=1, max_length=300)


class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: Literal["serper", "google_places", "gbizinfo"]
    keyword: str = Field(min_length=1, max_length=300)
    requested_count: int = Field(ge=1, le=30)
    repeat: bool = False


class StartReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReviewInput(StartReviewInput):
    session_id: UUID
    expected_version: int = Field(ge=0)
    outcome: str
    reason: str = Field(min_length=2, max_length=1000)
    evidence_url: str = Field(min_length=1, max_length=2048)
    entity_key: str = Field(default="", pattern=r"^[A-Za-z0-9_-]{0,100}$")
    duplicate_of: UUID | None = None


def access(db, user, benchmark_id, write=False):
    benchmark = db.get(RawBenchmark, benchmark_id)
    if not benchmark:
        raise HTTPException(404, "Benchmarkが見つかりません。")
    project_access(benchmark.project_id, db, user, write=write, raw_benchmark=True)
    return benchmark


def observation(db, user, snapshot_id):
    snapshot = db.get(RawLeadSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Raw候補が見つかりません。")
    run = db.get(RawQueryRun, snapshot.run_id)
    benchmark = access(db, user, run.benchmark_id, write=True)
    db.scalar(select(Project.id).where(Project.id == benchmark.project_id).with_for_update())
    return snapshot, run, benchmark


def public_review(row):
    return (
        {
            "version": row.version,
            "outcome": row.outcome,
            "reason": row.reason,
            "evidence_url": row.evidence_url,
            "entity_key": row.entity_key,
            "duplicate_of": row.duplicate_of,
            "reviewer": row.reviewer_id,
            "reviewed_at": row.reviewed_at,
            "duration_seconds": row.duration_seconds,
        }
        if row
        else None
    )


@router.get("/sources")
def sources(user: User = Depends(current_user)):
    return [
        {"source": "serper", "configured": bool(settings.serper_api_key), "pilot_allowed": True},
        {
            "source": "google_places",
            "configured": bool(settings.google_places_api_key),
            "pilot_allowed": False,
            "reason": "保存・利用条件の確認が必要です。Raw永続保存は未許可。",
        },
        {
            "source": "gbizinfo",
            "configured": bool(settings.gbizinfo_api_token),
            "pilot_allowed": True,
            "reason": "法人名検索です。業種検索・店舗母集団ではありません。",
        },
    ]


@router.post("", status_code=201)
def create(body: CreateInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    profile = TargetProfile(
        user_id=user.id,
        profile_name="RAW BENCHMARK",
        search_keywords=[],
        is_system=False,
        active=False,
    )
    db.add(profile)
    db.flush()
    project = Project(
        user_id=user.id,
        target_profile_id=profile.id,
        project_name=f"RAW BENCHMARK - {body.region} - {body.industry}"[:200],
        sales_objective="Raw Collection測定専用。営業・補完は実行しない。",
        region=body.region,
        status="draft",
    )
    db.add(project)
    db.flush()
    benchmark = RawBenchmark(
        project_id=project.id,
        created_by_user_id=user.id,
        region=body.region,
        industry=body.industry,
        definition_version="raw-repeat-v2",
        code_commit=commit_id(),
    )
    db.add(benchmark)
    db.commit()
    return {"id": benchmark.id, "project_id": project.id, "phase": "PILOT", "limit": 30}


@router.get("")
def listing(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(RawBenchmark)
        .join(Project)
        .where(accessible_project_condition(user.id))
        .order_by(RawBenchmark.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": r.id,
            "project_id": r.project_id,
            "region": r.region,
            "industry": r.industry,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def raw_candidate_key(snapshot):
    from app.services.raw_repeat import candidate_key

    return candidate_key(snapshot.payload, snapshot.id)


@router.get("/{benchmark_id}/report")
def summary(benchmark_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    benchmark = access(db, user, benchmark_id)
    value = report(db, benchmark)
    try:
        project_access(benchmark.project_id, db, user, raw_benchmark=True)
        value["can_review"] = True
    except HTTPException:
        value["can_review"] = False
    return value


@router.get("/{benchmark_id}/snapshots")
def snapshots(
    benchmark_id: UUID,
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    benchmark = access(db, user, benchmark_id)
    rows = db.scalars(
        select(RawLeadSnapshot)
        .join(RawQueryRun)
        .where(RawQueryRun.benchmark_id == benchmark.id)
        .order_by(RawQueryRun.ordinal, RawLeadSnapshot.position)
        .offset(offset)
        .limit(90)
    ).all()
    return [
        {
            "id": r.id,
            "payload": r.payload,
            "candidate_key": raw_candidate_key(r),
            "snapshot_hash": r.snapshot_hash,
            "review": public_review(latest_review(db, r.id)),
        }
        for r in rows
    ]


@router.post("/{benchmark_id}/queries", status_code=201)
def collect(
    benchmark_id: UUID,
    body: QueryInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    benchmark = access(db, user, benchmark_id, write=True)
    if body.source == "google_places":
        raise HTTPException(409, "Google Placesの永続保存条件が未確認のため実行できません。")
    if not (settings.serper_api_key if body.source == "serper" else settings.gbizinfo_api_token):
        raise HTTPException(409, "収集Sourceの認証情報が未設定です。")
    db.scalar(select(Project.id).where(Project.id == benchmark.project_id).with_for_update())
    runs = db.scalars(
        select(RawQueryRun)
        .where(RawQueryRun.benchmark_id == benchmark.id)
        .order_by(RawQueryRun.ordinal)
    ).all()
    if any(r.status == "RUNNING" for r in runs):
        raise HTTPException(409, "収集中です。再読込または中断状態を確認してください。")
    previous = [r for r in runs if r.source == body.source and r.keyword == body.keyword]
    if previous and not body.repeat:
        raise HTTPException(409, "同じSource/Queryです。反復測定を明示してください。")
    if body.repeat and not previous:
        raise HTTPException(409, "初回RunのないQueryは反復できません。")
    if previous and (
        benchmark.definition_version != "raw-repeat-v2"
        or len(previous) >= 3
        or body.requested_count != previous[0].requested_count
        or previous[-1].status != "COMPLETED"
        or any(r.code_commit != commit_id() for r in previous)
    ):
        raise HTTPException(409, "同条件・同commitの成功Runだけ最大3回まで反復できます。")
    base_count = sum(r.requested_count for r in runs if r.repeat_index == 1)
    if not previous and base_count + body.requested_count > 30:
        raise HTTPException(
            409, "Pilotの合計依頼上限30件を超えます。Full Benchmarkへ自動拡大しません。"
        )
    if body.keyword not in {r.keyword for r in runs} and len({r.keyword for r in runs}) >= 4:
        raise HTTPException(409, "Pilot検索語は最大4種類です。")
    run = RawQueryRun(
        benchmark_id=benchmark.id,
        ordinal=len(runs) + 1,
        repeat_index=len(previous) + 1,
        source=body.source,
        keyword=body.keyword,
        query=f"{body.keyword} {benchmark.region}".strip(),
        requested_count=body.requested_count,
        code_commit=commit_id(),
    )
    db.add(run)
    db.commit()
    error = ""
    with capturing() as raw:
        try:
            provider = search_serper if body.source == "serper" else search_gbizinfo
            provider(body.keyword, benchmark.region, body.requested_count)
        except ExternalServiceError as exc:
            error = exc.public_message
        except Exception:
            error = "Raw収集処理に失敗しました。内部情報は表示しません。"
    db.scalar(select(Project.id).where(Project.id == benchmark.project_id).with_for_update())
    db.refresh(run)
    now = datetime.now(timezone.utc)
    for index, fields in enumerate(raw[: body.requested_count], 1):
        source_payload_hash = digest(fields)
        redacted_urls = []
        # Do not retain credentials/tracking queries embedded in provider URLs.
        for key in ("website", "reference_url"):
            try:
                p = urlsplit(fields[key])
                sanitized = urlunsplit((p.scheme, p.netloc.rsplit("@", 1)[-1], p.path, "", ""))
                if sanitized != fields[key]:
                    redacted_urls.append(key)
                fields[key] = sanitized
            except ValueError:
                fields[key] = ""
        payload = {
            **fields,
            "benchmark_id": str(benchmark.id),
            "repeat_index": run.repeat_index,
            "source": run.source,
            "source_keyword": run.keyword,
            "source_query": run.query,
            "query_region": benchmark.region,
            "query_industry": benchmark.industry,
            "collection_job_id": str(run.id),
            "collection_timestamp": now.isoformat(),
            "position": index,
            "source_payload_hash": source_payload_hash,
            "redacted_url_fields": redacted_urls,
        }
        db.add(
            RawLeadSnapshot(
                run_id=run.id,
                position=index,
                payload=payload,
                snapshot_hash=digest(payload),
                collected_at=now,
            )
        )
    if run.status != "CANCELLED":
        run.status = "FAILED" if error else "COMPLETED"
    run.error = error
    run.finished_at = now
    db.commit()
    return {
        "job_id": run.id,
        "status": run.status,
        "found": len(raw[: body.requested_count]),
        "error": error,
        "completion_jobs": 0,
        "execution_allowed": False,
    }


@router.post("/{benchmark_id}/queries/{run_id}/cancel")
def cancel(
    benchmark_id: UUID,
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    benchmark = access(db, user, benchmark_id, write=True)
    db.scalar(select(Project.id).where(Project.id == benchmark.project_id).with_for_update())
    run = db.get(RawQueryRun, run_id)
    if not run or run.benchmark_id != benchmark.id:
        raise HTTPException(404, "収集ジョブが見つかりません。")
    if run.status != "RUNNING":
        raise HTTPException(409, "実行中のジョブではありません。")
    run.status = "CANCELLED"
    db.commit()
    return {
        "status": run.status,
        "warning": "通信済みAPIは取り消せません。返却済み候補は保存されます。",
    }


@router.post("/snapshots/{snapshot_id}/review-start", status_code=201)
def start_review(
    snapshot_id: UUID,
    body: StartReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    snapshot, _, _ = observation(db, user, snapshot_id)
    if snapshot.snapshot_hash != body.snapshot_hash:
        raise HTTPException(409, "Snapshotが一致しません。")
    session = RawReviewSession(
        snapshot_id=snapshot.id,
        user_id=user.id,
        snapshot_hash=snapshot.snapshot_hash,
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()
    return {"session_id": session.id, "started_at": session.started_at}


@router.post("/snapshots/{snapshot_id}/reviews", status_code=201)
def review(
    snapshot_id: UUID,
    body: ReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    snapshot, run, _ = observation(db, user, snapshot_id)
    previous = latest_review(db, snapshot.id)
    if body.snapshot_hash != snapshot.snapshot_hash or body.expected_version != (
        previous.version if previous else 0
    ):
        raise HTTPException(409, "Snapshotまたはレビュー版が変わりました。")
    session = db.get(RawReviewSession, body.session_id)
    now = datetime.now(timezone.utc)
    if (
        not session
        or session.user_id != user.id
        or session.snapshot_id != snapshot.id
        or (session.finished_at or session.snapshot_hash != snapshot.snapshot_hash)
        or not 0 <= (now - session.started_at).total_seconds() <= 14400
        or db.scalar(select(RawPairReview.id).where(RawPairReview.session_id == body.session_id))
    ):
        raise HTTPException(409, "確認開始記録が無効・使用済み・失効しています。")
    if body.outcome not in OUTCOMES:
        raise HTTPException(422, "判定結果が正しくありません。")
    try:
        parsed = urlsplit(body.evidence_url)
        evidence = normalize_destination("form", body.evidence_url)
        if parsed.query or parsed.fragment:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPException(422, "根拠は秘密情報のない公開URLを指定してください。") from None
    entity = body.entity_key if body.outcome == "CORRECT" else ""
    if body.outcome == "CORRECT" and not entity:
        raise HTTPException(
            422, "正しい店舗の照合用IDを入力してください。同じ店舗は同じIDを使用します。"
        )
    if body.outcome == "DUPLICATE":
        original = db.get(RawLeadSnapshot, body.duplicate_of) if body.duplicate_of else None
        original_run = db.get(RawQueryRun, original.run_id) if original else None
        original_review = latest_review(db, original.id) if original else None
        if (
            not original
            or original.id == snapshot.id
            or not original_run
            or (original_run.benchmark_id != run.benchmark_id)
            or not original_review
            or not original_review.entity_key
            or (original_run.ordinal, original.position) >= (run.ordinal, snapshot.position)
        ):
            raise HTTPException(422, "同じBenchmark内の先に確認した店舗候補を指定してください。")
        entity = original_review.entity_key
    elif body.duplicate_of:
        raise HTTPException(422, "重複以外に重複先は指定できません。")
    row = RawLeadReview(
        snapshot_id=snapshot.id,
        session_id=session.id,
        reviewer_id=user.id,
        version=body.expected_version + 1,
        snapshot_hash=snapshot.snapshot_hash,
        outcome=body.outcome,
        reason=body.reason,
        evidence_url=evidence,
        entity_key=entity,
        duplicate_of=body.duplicate_of,
        duration_seconds=int((now - session.started_at).total_seconds()),
        reviewed_at=now,
    )
    session.finished_at = now
    db.add(row)
    db.commit()
    return {"review": public_review(row), "execution_allowed": False}
