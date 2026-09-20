"""add smtp delivery limits"""

import sqlalchemy as sa
from alembic import op

revision = "aa7c3d92e5b1"
down_revision = "9e5a8b40d12f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "smtp_settings",
        sa.Column("max_emails_per_day", sa.Integer(), server_default="100", nullable=False),
    )
    op.add_column(
        "smtp_settings",
        sa.Column("minimum_interval_seconds", sa.Integer(), server_default="60", nullable=False),
    )
    op.alter_column("smtp_settings", "max_emails_per_day", server_default=None)
    op.alter_column("smtp_settings", "minimum_interval_seconds", server_default=None)
    op.create_check_constraint(
        "ck_smtp_settings_daily_limit",
        "smtp_settings",
        "max_emails_per_day BETWEEN 1 AND 10000",
    )
    op.create_check_constraint(
        "ck_smtp_settings_interval",
        "smtp_settings",
        "minimum_interval_seconds BETWEEN 0 AND 3600",
    )


def downgrade():
    op.drop_constraint("ck_smtp_settings_interval", "smtp_settings", type_="check")
    op.drop_constraint("ck_smtp_settings_daily_limit", "smtp_settings", type_="check")
    op.drop_column("smtp_settings", "minimum_interval_seconds")
    op.drop_column("smtp_settings", "max_emails_per_day")
