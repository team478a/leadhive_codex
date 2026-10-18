"""Persist browser-form runs and bounded screenshots.

Revision ID: b4f0a7c1e2d9
Revises: 4f7b2a9c1d30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4f0a7c1e2d9"
down_revision: str | None = "4f7b2a9c1d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_form_delivery_method", "form_deliveries", type_="check")
    op.create_check_constraint(
        "ck_form_delivery_method",
        "form_deliveries",
        "delivery_method IN ('direct', 'codex_assisted', 'adapter', 'browser')",
    )
    op.create_table(
        "browser_form_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("form_profile_id", sa.Uuid(), nullable=True),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("dispatch_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("form_url", sa.Text(), nullable=False),
        sa.Column("form_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("mode IN ('dry_run','submit')", name="ck_browser_form_run_mode"),
        sa.CheckConstraint(
            "status IN ('queued','checking','submitted','failed','unknown','blocked',"
            "'cancelled','dry_run_completed')",
            name="ck_browser_form_run_status",
        ),
        sa.CheckConstraint(
            "(mode='submit' AND dispatch_id IS NOT NULL) OR "
            "(mode='dry_run' AND dispatch_id IS NULL)",
            name="ck_browser_form_run_dispatch_mode",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["form_profile_id"], ["form_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["draft_id"], ["outreach_drafts.id"]),
        sa.ForeignKeyConstraint(
            ["dispatch_id"], ["approved_form_dispatches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dispatch_id", name="uq_browser_form_run_dispatch"),
    )
    for column in ("project_id", "company_id", "form_profile_id", "status", "started_at"):
        op.create_index(f"ix_browser_form_runs_{column}", "browser_form_runs", [column])

    op.create_table(
        "browser_form_screenshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column(
            "content_type", sa.String(length=30), nullable=False, server_default="image/jpeg"
        ),
        sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "phase IN ('before_submit','after_submit')", name="ck_browser_form_screenshot_phase"
        ),
        sa.CheckConstraint(
            "octet_length(image_bytes) BETWEEN 1 AND 200000",
            name="ck_browser_form_screenshot_size",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["browser_form_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "phase", name="uq_browser_form_screenshot_run_phase"),
    )
    op.create_index("ix_browser_form_screenshots_run_id", "browser_form_screenshots", ["run_id"])
    op.create_index(
        "ix_browser_form_screenshots_created_at", "browser_form_screenshots", ["created_at"]
    )

    op.drop_constraint("ck_outreach_draft_approval_type", "outreach_draft_approvals", type_="check")
    op.create_check_constraint(
        "ck_outreach_draft_approval_type",
        "outreach_draft_approvals",
        "approval_type IN ('email', 'form_direct', 'form_codex', 'form_adapter', 'browser_form')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_outreach_draft_approval_type", "outreach_draft_approvals", type_="check")
    op.create_check_constraint(
        "ck_outreach_draft_approval_type",
        "outreach_draft_approvals",
        "approval_type IN ('email', 'form_direct', 'form_codex', 'form_adapter')",
    )
    op.drop_constraint("ck_form_delivery_method", "form_deliveries", type_="check")
    op.create_check_constraint(
        "ck_form_delivery_method",
        "form_deliveries",
        "delivery_method IN ('direct', 'codex_assisted', 'adapter')",
    )
    op.drop_index("ix_browser_form_screenshots_created_at", table_name="browser_form_screenshots")
    op.drop_index("ix_browser_form_screenshots_run_id", table_name="browser_form_screenshots")
    op.drop_table("browser_form_screenshots")
    for column in ("project_id", "company_id", "form_profile_id", "status", "started_at"):
        op.drop_index(f"ix_browser_form_runs_{column}", table_name="browser_form_runs")
    op.drop_table("browser_form_runs")
