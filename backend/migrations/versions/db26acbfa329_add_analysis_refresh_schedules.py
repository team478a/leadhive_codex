"""add analysis refresh schedules"""

import sqlalchemy as sa
from alembic import op

revision = "db26acbfa329"
down_revision = "69fca6fd2dab"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_refresh_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("stale_days", sa.Integer(), nullable=False),
        sa.Column("batch_limit", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "batch_limit BETWEEN 1 AND 100", name="ck_analysis_refresh_schedule_batch_limit"
        ),
        sa.CheckConstraint(
            "interval_hours BETWEEN 1 AND 720", name="ck_analysis_refresh_schedule_interval"
        ),
        sa.CheckConstraint(
            "stale_days BETWEEN 1 AND 3650", name="ck_analysis_refresh_schedule_stale_days"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_refresh_schedules_next_run_at",
        "analysis_refresh_schedules",
        ["next_run_at"],
    )
    op.create_index(
        "ix_analysis_refresh_schedules_project_id",
        "analysis_refresh_schedules",
        ["project_id"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "ix_analysis_refresh_schedules_project_id",
        table_name="analysis_refresh_schedules",
    )
    op.drop_index(
        "ix_analysis_refresh_schedules_next_run_at",
        table_name="analysis_refresh_schedules",
    )
    op.drop_table("analysis_refresh_schedules")
