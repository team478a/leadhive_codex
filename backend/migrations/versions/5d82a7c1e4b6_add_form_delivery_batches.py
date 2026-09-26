"""add approved bulk form delivery batches"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5d82a7c1e4b6"
down_revision = "3a72c4e8d1f5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_delivery_batches",
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
        sa.Column("status", sa.String(20), nullable=False, server_default="ready"),
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
            "status IN ('ready', 'running', 'completed', 'cancelled')", name="ck_form_batch_status"
        ),
    )
    for column in ("project_id", "template_id", "created_by_user_id", "status"):
        op.create_index(f"ix_form_delivery_batches_{column}", "form_delivery_batches", [column])
    op.create_table(
        "form_delivery_batch_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("form_delivery_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outreach_drafts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "form_delivery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("form_deliveries.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("batch_id", "company_id", name="uq_form_batch_item_company"),
        sa.CheckConstraint(
            "status IN ('queued', 'submitted', 'failed', 'manual_required', 'skipped')",
            name="ck_form_batch_item_status",
        ),
    )
    for column in ("batch_id", "company_id", "draft_id", "form_delivery_id", "status"):
        op.create_index(
            f"ix_form_delivery_batch_items_{column}", "form_delivery_batch_items", [column]
        )


def downgrade():
    op.drop_table("form_delivery_batch_items")
    op.drop_table("form_delivery_batches")
