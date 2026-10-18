from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import BrowserFormScreenshot

MAX_SCREENSHOT_BYTES = 200_000


def store_screenshot(db, run_id, phase, image_bytes):
    if (
        phase not in {"before_submit", "after_submit"}
        or not isinstance(image_bytes, bytes)
        or not image_bytes.startswith(b"\xff\xd8")
        or not image_bytes.endswith(b"\xff\xd9")
        or len(image_bytes) > MAX_SCREENSHOT_BYTES
    ):
        raise ValueError("Browser screenshots must be JPEG images no larger than 200 KB.")
    row = db.scalar(
        select(BrowserFormScreenshot)
        .where(BrowserFormScreenshot.run_id == run_id, BrowserFormScreenshot.phase == phase)
        .with_for_update()
    )
    if row is None:
        row = BrowserFormScreenshot(
            run_id=run_id,
            phase=phase,
            content_type="image/jpeg",
            image_bytes=image_bytes,
        )
        db.add(row)
    else:
        row.content_type, row.image_bytes = "image/jpeg", image_bytes
    return row


def serialized(db, runs):
    run_ids = [run.id for run in runs]
    phases = {}
    if run_ids:
        retained_after = datetime.now(timezone.utc) - timedelta(days=90)
        for run_id, phase in db.execute(
            select(BrowserFormScreenshot.run_id, BrowserFormScreenshot.phase).where(
                BrowserFormScreenshot.run_id.in_(run_ids),
                BrowserFormScreenshot.created_at >= retained_after,
            )
        ):
            phases.setdefault(run_id, set()).add(phase)
    return [
        {
            "id": run.id,
            "project_id": run.project_id,
            "company_id": run.company_id,
            "form_profile_id": run.form_profile_id,
            "draft_id": run.draft_id,
            "dispatch_id": run.dispatch_id,
            "mode": run.mode,
            "status": run.status,
            "form_url": run.form_url,
            "form_fingerprint": run.form_fingerprint,
            "reason": run.reason,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "has_before_screenshot": "before_submit" in phases.get(run.id, set()),
            "has_after_screenshot": "after_submit" in phases.get(run.id, set()),
            "screenshot_before_url": f"/browser-form-runs/{run.id}/screenshots/before_submit"
            if "before_submit" in phases.get(run.id, set())
            else None,
            "screenshot_after_url": f"/browser-form-runs/{run.id}/screenshots/after_submit"
            if "after_submit" in phases.get(run.id, set())
            else None,
        }
        for run in runs
    ]
