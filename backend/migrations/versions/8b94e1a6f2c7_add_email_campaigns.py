"""add email campaigns and unsubscribe tokens"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8b94e1a6f2c7"
down_revision = "5d82a7c1e4b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outreach_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("followup_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'paused', 'completed')", name="ck_email_campaign_status"
        ),
    )
    for column in ("project_id", "template_id", "created_by_user_id", "status"):
        op.create_index(f"ix_email_campaigns_{column}", "email_campaigns", [column])
    op.add_column(
        "email_deliveries",
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("email_campaigns.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("email_deliveries", sa.Column("unsubscribe_token", sa.String(64), nullable=True))
    op.execute(
        "UPDATE email_deliveries SET unsubscribe_token = md5(random()::text || clock_timestamp()::text || id::text)"
    )
    op.alter_column("email_deliveries", "unsubscribe_token", nullable=False)
    op.create_index("ix_email_deliveries_campaign_id", "email_deliveries", ["campaign_id"])
    op.create_index(
        "ix_email_deliveries_unsubscribe_token",
        "email_deliveries",
        ["unsubscribe_token"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_email_deliveries_unsubscribe_token", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_campaign_id", table_name="email_deliveries")
    op.drop_column("email_deliveries", "unsubscribe_token")
    op.drop_column("email_deliveries", "campaign_id")
    op.drop_table("email_campaigns")
