"""add approved form delivery"""

import sqlalchemy as sa
from alembic import op

revision = "d83e6f149ab2"
down_revision = "aa7c3d92e5b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("form_url", sa.Text(), nullable=False),
        sa.Column("action_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=False),
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
        sa.CheckConstraint("status IN ('submitted', 'failed')", name="ck_form_delivery_status"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["draft_id"], ["outreach_drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", name="uq_form_delivery_draft"),
    )
    op.create_index("ix_form_deliveries_company_id", "form_deliveries", ["company_id"])
    op.create_index(
        "ix_form_deliveries_created_by_user_id", "form_deliveries", ["created_by_user_id"]
    )
    op.create_index("ix_form_deliveries_draft_id", "form_deliveries", ["draft_id"])
    op.create_index("ix_form_deliveries_status", "form_deliveries", ["status"])


def downgrade():
    op.drop_index("ix_form_deliveries_status", table_name="form_deliveries")
    op.drop_index("ix_form_deliveries_draft_id", table_name="form_deliveries")
    op.drop_index("ix_form_deliveries_created_by_user_id", table_name="form_deliveries")
    op.drop_index("ix_form_deliveries_company_id", table_name="form_deliveries")
    op.drop_table("form_deliveries")
