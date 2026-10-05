"""Persist conservative administrator-controlled form dispatch limits."""

import sqlalchemy as sa
from alembic import op

revision = "f9c36fb4d750"
down_revision = "f8b25ea3c649"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "form_dispatch_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("hourly_limit", sa.Integer(), nullable=False),
        sa.Column("minimum_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_form_limits_singleton"),
        sa.CheckConstraint(
            "daily_limit BETWEEN 1 AND 1000 AND hourly_limit BETWEEN 1 AND 100 "
            "AND minimum_interval_seconds BETWEEN 60 AND 86400",
            name="ck_form_limits_range",
        ),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": 1,
                "daily_limit": 30,
                "hourly_limit": 5,
                "minimum_interval_seconds": 60,
                "paused": False,
                "version": 1,
            }
        ],
    )


def downgrade():
    op.drop_table("form_dispatch_limits")
