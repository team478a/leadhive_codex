"""add background bulk form delivery"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e318a9c4d802"
down_revision = "8b94e1a6f2c7"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery')",
    )
    op.add_column(
        "form_delivery_batches",
        sa.Column("operation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_form_batch_operation_job",
        "form_delivery_batches",
        "operation_jobs",
        ["operation_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_form_delivery_batches_operation_job_id",
        "form_delivery_batches",
        ["operation_job_id"],
    )
    op.add_column(
        "form_delivery_batch_items",
        sa.Column("codex_status", sa.String(20), nullable=False, server_default="open"),
    )
    op.add_column(
        "form_delivery_batch_items",
        sa.Column("codex_assignee", sa.String(320), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_form_delivery_batch_items_codex_status", "form_delivery_batch_items", ["codex_status"]
    )


def downgrade():
    op.drop_index(
        "ix_form_delivery_batch_items_codex_status", table_name="form_delivery_batch_items"
    )
    op.drop_column("form_delivery_batch_items", "codex_assignee")
    op.drop_column("form_delivery_batch_items", "codex_status")
    op.drop_index("ix_form_delivery_batches_operation_job_id", table_name="form_delivery_batches")
    op.drop_constraint("fk_form_batch_operation_job", "form_delivery_batches", type_="foreignkey")
    op.drop_column("form_delivery_batches", "operation_job_id")
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis')",
    )
