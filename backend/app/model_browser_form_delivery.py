import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BrowserFormRun(Base):
    __tablename__ = "browser_form_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('dry_run','submit')", name="ck_browser_form_run_mode"),
        CheckConstraint(
            "status IN ('queued','checking','submitted','failed','unknown','blocked',"
            "'cancelled','dry_run_completed')",
            name="ck_browser_form_run_status",
        ),
        CheckConstraint(
            "(mode='submit' AND dispatch_id IS NOT NULL) OR "
            "(mode='dry_run' AND dispatch_id IS NULL)",
            name="ck_browser_form_run_dispatch_mode",
        ),
        UniqueConstraint("dispatch_id", name="uq_browser_form_run_dispatch"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    form_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_profiles.id", ondelete="SET NULL"), index=True
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outreach_drafts.id"))
    dispatch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approved_form_dispatches.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    payload_snapshot: Mapped[dict] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    form_url: Mapped[str] = mapped_column(Text)
    form_fingerprint: Mapped[str] = mapped_column(String(64))
    worker_id: Mapped[uuid.UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BrowserFormScreenshot(Base):
    __tablename__ = "browser_form_screenshots"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('before_submit','after_submit')", name="ck_browser_form_screenshot_phase"
        ),
        CheckConstraint(
            "octet_length(image_bytes) BETWEEN 1 AND 200000",
            name="ck_browser_form_screenshot_size",
        ),
        UniqueConstraint("run_id", "phase", name="uq_browser_form_screenshot_run_phase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("browser_form_runs.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[str] = mapped_column(String(20))
    content_type: Mapped[str] = mapped_column(String(30), default="image/jpeg")
    image_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
