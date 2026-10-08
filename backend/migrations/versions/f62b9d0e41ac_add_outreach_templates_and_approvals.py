"""add outreach templates and approvals"""

import sqlalchemy as sa
from alembic import op

revision = "f62b9d0e41ac"
down_revision = "e54a7c8d91bf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outreach_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
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
            "channel IN ('email', 'form', 'sns')", name="ck_outreach_template_channel"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_templates_project_id", "outreach_templates", ["project_id"])
    op.create_index(
        "ix_outreach_templates_created_by_user_id", "outreach_templates", ["created_by_user_id"]
    )
    op.create_table(
        "outreach_draft_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approval_type", sa.String(length=30), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "approval_type IN ('email', 'form_direct', 'form_codex')",
            name="ck_outreach_draft_approval_type",
        ),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["draft_id"], ["outreach_drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outreach_draft_approvals_draft_id", "outreach_draft_approvals", ["draft_id"]
    )
    op.create_index(
        "ix_outreach_draft_approvals_approved_by_user_id",
        "outreach_draft_approvals",
        ["approved_by_user_id"],
    )


def downgrade():
    op.drop_index(
        "ix_outreach_draft_approvals_approved_by_user_id", table_name="outreach_draft_approvals"
    )
    op.drop_index("ix_outreach_draft_approvals_draft_id", table_name="outreach_draft_approvals")
    op.drop_table("outreach_draft_approvals")
    op.drop_index("ix_outreach_templates_created_by_user_id", table_name="outreach_templates")
    op.drop_index("ix_outreach_templates_project_id", table_name="outreach_templates")
    op.drop_table("outreach_templates")
