from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    BrowserFormRun,
    BrowserFormScreenshot,
    Company,
    FormProfile,
    OutreachDraft,
    User,
)
from app.project_access import project_access
from app.security import current_user
from app.services.browser_form_plan import canonical_plan, plan_hash
from app.services.browser_form_runs import serialized

router = APIRouter(prefix="/api", tags=["Browser form delivery"])


def _enabled():
    if not settings.browser_form_delivery_enabled:
        raise HTTPException(409, "ブラウザーフォーム実行は既定でOFFです。")


def _company_for_profile(db: Session, profile_id: UUID, user: User, *, lock=False):
    query = select(FormProfile).where(FormProfile.id == profile_id)
    if lock:
        query = query.with_for_update()
    profile = db.scalar(query)
    if not profile:
        raise HTTPException(404, "フォーム解析が見つかりません。")
    company = db.get(Company, profile.company_id)
    if not company:
        raise HTTPException(404, "企業が見つかりません。")
    project_access(company.project_id, db, user)
    return company, profile


@router.post("/form-profiles/{profile_id}/browser-form-dry-run", status_code=202)
def enqueue_browser_dry_run(
    profile_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _enabled()
    company, profile = _company_for_profile(db, profile_id, user, lock=True)
    from app.services.browser_form_preparation import preparation

    draft = db.scalar(
        select(OutreachDraft)
        .where(OutreachDraft.company_id == company.id, OutreachDraft.channel == "form")
        .order_by(OutreachDraft.updated_at.desc(), OutreachDraft.id.desc())
        .limit(1)
    )
    if not draft:
        raise HTTPException(409, "フォーム用Draftがありません。")
    proposal, _preview = preparation(db, company, draft)
    plan = proposal.browser_form_plan
    if not plan or plan.form_profile_id != profile.id:
        raise HTTPException(409, "確認済みフォームの送信計画を作成できません。")
    digest = plan_hash(plan)
    active = db.scalar(
        select(BrowserFormRun)
        .where(
            BrowserFormRun.mode == "dry_run",
            BrowserFormRun.company_id == company.id,
            BrowserFormRun.status.in_(("queued", "checking")),
        )
        .order_by(BrowserFormRun.created_at.desc(), BrowserFormRun.id)
        .limit(1)
        .with_for_update()
    )
    if active:
        return {"id": active.id, "status": active.status, "mode": active.mode}
    run = BrowserFormRun(
        project_id=company.project_id,
        company_id=company.id,
        form_profile_id=profile.id,
        draft_id=draft.id,
        dispatch_id=None,
        created_by_user_id=user.id,
        mode="dry_run",
        status="queued",
        payload_snapshot={"mode": "dry_run", "browser_form_plan": canonical_plan(plan)},
        payload_hash=digest,
        form_url=plan.form_url,
        form_fingerprint=plan.form_fingerprint,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"id": run.id, "status": run.status, "mode": run.mode}


@router.get("/projects/{project_id}/browser-form-runs")
def list_project_runs(
    project_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_access(project_id, db, user, write=False)
    rows = db.scalars(
        select(BrowserFormRun)
        .where(BrowserFormRun.project_id == project_id)
        .order_by(BrowserFormRun.created_at.desc(), BrowserFormRun.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return serialized(db, rows)


@router.get("/companies/{company_id}/browser-form-runs")
def list_company_runs(
    company_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "企業が見つかりません。")
    project_access(company.project_id, db, user, write=False)
    rows = db.scalars(
        select(BrowserFormRun)
        .where(BrowserFormRun.company_id == company_id)
        .order_by(BrowserFormRun.created_at.desc(), BrowserFormRun.id)
        .limit(limit)
    ).all()
    return serialized(db, rows)


@router.get("/browser-form-runs/{run_id}/screenshots/{phase}")
def get_screenshot(
    run_id: UUID,
    phase: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if phase not in {"before_submit", "after_submit"}:
        raise HTTPException(404, "画面証跡がありません。")
    run = db.get(BrowserFormRun, run_id)
    if not run:
        raise HTTPException(404, "実行記録が見つかりません。")
    project_access(run.project_id, db, user, write=False)
    screenshot = db.scalar(
        select(BrowserFormScreenshot).where(
            BrowserFormScreenshot.run_id == run_id,
            BrowserFormScreenshot.phase == phase,
            BrowserFormScreenshot.created_at >= datetime.now(timezone.utc) - timedelta(days=90),
        )
    )
    if not screenshot:
        raise HTTPException(404, "画面証跡の保持期限が過ぎたか、記録がありません。")
    return Response(
        content=screenshot.image_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/browser-form-runs/{run_id}/cancel")
def cancel_dry_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    run = db.scalar(select(BrowserFormRun).where(BrowserFormRun.id == run_id).with_for_update())
    if not run:
        raise HTTPException(404, "実行記録が見つかりません。")
    project_access(run.project_id, db, user)
    if run.mode != "dry_run" or run.status not in {"queued", "checking"}:
        raise HTTPException(409, "開始後の送信・終了済み実行は取消できません。")
    run.status = "cancelled"
    run.reason = "利用者がdry-runを取り消しました。"
    run.finished_at = datetime.now(timezone.utc)
    run.worker_id, run.lease_expires_at = None, None
    run.payload_snapshot = {"mode": run.mode}
    db.commit()
    return {"id": run.id, "status": run.status}
