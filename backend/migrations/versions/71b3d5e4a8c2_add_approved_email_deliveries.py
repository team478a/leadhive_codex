"""add approved email deliveries"""

import sqlalchemy as sa
from alembic import op

revision = "71b3d5e4a8c2"
down_revision = "7044c8210a16"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("recipient_name", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'sent', 'failed', 'cancelled')", name="ck_email_delivery_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_email_delivery_attempt_count"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["draft_id"], ["outreach_drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", name="uq_email_delivery_draft"),
    )
    op.create_index("ix_email_deliveries_company_id", "email_deliveries", ["company_id"])
    op.create_index("ix_email_deliveries_created_by_user_id", "email_deliveries", ["created_by_user_id"])
    op.create_index("ix_email_deliveries_draft_id", "email_deliveries", ["draft_id"])
    op.create_index("ix_email_deliveries_lease_expires_at", "email_deliveries", ["lease_expires_at"])
    op.create_index("ix_email_deliveries_scheduled_for", "email_deliveries", ["scheduled_for"])
    op.create_index("ix_email_deliveries_status", "email_deliveries", ["status"])


def downgrade():
    op.drop_index("ix_email_deliveries_status", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_scheduled_for", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_lease_expires_at", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_draft_id", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_created_by_user_id", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_company_id", table_name="email_deliveries")
    op.drop_table("email_deliveries")
